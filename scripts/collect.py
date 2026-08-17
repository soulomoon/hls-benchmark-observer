#!/usr/bin/env python3
"""Validate benchmark artifacts and append them to the durable history."""

from __future__ import annotations

import argparse
import copy
import csv
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
COMMIT = re.compile(r"^[0-9a-f]{40}$")

RESULT_FIELDS = [
    "configuration",
    "benchmark",
    "success",
    "samples",
    "startup_ms",
    "setup_ms",
    "user_time_ms",
    "delayed_time_ms",
    "first_build_ms",
    "average_response_ms",
    "total_time_ms",
    "rules_built",
    "rules_changed",
    "rules_visited",
    "rules_total",
    "rule_edges",
    "ghc_rebuilds",
    "max_residency_mb",
    "allocated_mb",
]

INTEGER_RESULT_FIELDS = {
    "samples",
    "rules_built",
    "rules_changed",
    "rules_visited",
    "rules_total",
    "rule_edges",
    "ghc_rebuilds",
}

NUMBER_RESULT_FIELDS = {
    "startup_ms",
    "setup_ms",
    "user_time_ms",
    "delayed_time_ms",
    "first_build_ms",
    "average_response_ms",
    "total_time_ms",
    "max_residency_mb",
    "allocated_mb",
}

CSV_FIELDS = [
    "measurement_id",
    "measured_at",
    "workflow_repository",
    "run_id",
    "run_attempt",
    "run_url",
    "upstream_repository",
    "upstream_ref",
    "upstream_commit",
    "commit_url",
    "ghc",
    "example",
    "runner_os",
    "runner_arch",
    "runner_image",
    "runner_image_version",
    *RESULT_FIELDS,
]


class CollectionError(ValueError):
    pass


def nested(document: dict[str, Any], *path: str) -> Any:
    current: Any = document
    for component in path:
        if not isinstance(current, dict) or component not in current:
            raise CollectionError(f"missing manifest field: {'.'.join(path)}")
        current = current[component]
    return current


def utc_timestamp(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as error:
        raise CollectionError(f"invalid measurement timestamp: {value!r}") from error
    if parsed.tzinfo is None:
        raise CollectionError("measurement timestamp must include a UTC offset")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def validate_result(result: Any, source: Path) -> None:
    if not isinstance(result, dict):
        raise CollectionError(f"{source}: result rows must be objects")
    missing = [field for field in RESULT_FIELDS if field not in result]
    if missing:
        raise CollectionError(f"{source}: result row missing fields: {', '.join(missing)}")
    if result.get("version") != "HEAD":
        raise CollectionError(f"{source}: observer artifacts must measure HEAD")
    if not isinstance(result["success"], bool):
        raise CollectionError(f"{source}: result success must be a boolean")
    for field in ("configuration", "benchmark"):
        if not isinstance(result[field], str) or not result[field]:
            raise CollectionError(f"{source}: result {field} must be non-empty")
    for field in INTEGER_RESULT_FIELDS:
        value = result[field]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise CollectionError(f"{source}: result {field} must be a non-negative integer")
    if result["samples"] == 0:
        raise CollectionError(f"{source}: result samples must be greater than zero")
    for field in NUMBER_RESULT_FIELDS:
        value = result[field]
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value < 0
        ):
            raise CollectionError(f"{source}: result {field} must be a finite non-negative number")


def validate_manifest(
    source: Path,
    *,
    expected_repository: str,
    expected_run_id: int,
    expected_run_attempt: int,
    expected_upstream_repository: str,
    expected_upstream_commit: str,
) -> dict[str, Any]:
    try:
        document = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CollectionError(f"cannot read {source}: {error}") from error

    if not isinstance(document, dict) or document.get("schema_version") != 1:
        raise CollectionError(f"{source}: unsupported manifest schema")

    workflow_repository = nested(document, "workflow", "repository")
    run_id = nested(document, "workflow", "run_id")
    run_attempt = nested(document, "workflow", "run_attempt")
    artifact_name = nested(document, "workflow", "artifact_name")
    run_url = nested(document, "workflow", "run_url")
    upstream_repository = nested(document, "upstream", "repository")
    upstream_commit = nested(document, "upstream", "commit")
    upstream_ref = nested(document, "upstream", "ref")
    commit_url = nested(document, "upstream", "commit_url")
    measured_at = nested(document, "measurement", "timestamp")

    expected = {
        "workflow.repository": (workflow_repository, expected_repository),
        "workflow.run_id": (run_id, expected_run_id),
        "workflow.run_attempt": (run_attempt, expected_run_attempt),
        "upstream.repository": (upstream_repository, expected_upstream_repository),
        "upstream.commit": (upstream_commit, expected_upstream_commit),
    }
    for field, (actual, wanted) in expected.items():
        if actual != wanted:
            raise CollectionError(f"{source}: {field} is {actual!r}, expected {wanted!r}")

    if REPOSITORY.fullmatch(workflow_repository) is None:
        raise CollectionError(f"{source}: invalid workflow repository")
    if REPOSITORY.fullmatch(upstream_repository) is None:
        raise CollectionError(f"{source}: invalid upstream repository")
    if not isinstance(upstream_commit, str) or COMMIT.fullmatch(upstream_commit) is None:
        raise CollectionError(f"{source}: invalid upstream commit")
    if not isinstance(upstream_ref, str) or not upstream_ref:
        raise CollectionError(f"{source}: upstream ref must be non-empty")
    expected_run_url = f"https://github.com/{workflow_repository}/actions/runs/{run_id}"
    if run_url != expected_run_url:
        raise CollectionError(f"{source}: workflow run URL does not match its identity")
    expected_commit_url = f"https://github.com/{upstream_repository}/commit/{upstream_commit}"
    if commit_url != expected_commit_url:
        raise CollectionError(f"{source}: upstream commit URL does not match its identity")
    if not isinstance(artifact_name, str) or not artifact_name.startswith("observer-benchmark-"):
        raise CollectionError(f"{source}: invalid artifact name")
    if source.parent.name != artifact_name:
        raise CollectionError(
            f"{source}: artifact directory {source.parent.name!r} does not match {artifact_name!r}"
        )

    document["measurement"]["timestamp"] = utc_timestamp(measured_at)
    for field in ("ghc", "example"):
        value = nested(document, "measurement", field)
        if not isinstance(value, str) or not value:
            raise CollectionError(f"{source}: measurement.{field} must be non-empty")
    expected_artifact_name = (
        f"observer-benchmark-{document['measurement']['example']}-ghc-"
        f"{document['measurement']['ghc']}"
    )
    if artifact_name != expected_artifact_name:
        raise CollectionError(f"{source}: artifact name does not match its matrix coordinate")
    runner = nested(document, "measurement", "runner")
    if not isinstance(runner, dict):
        raise CollectionError(f"{source}: measurement.runner must be an object")
    for field in ("os", "arch", "image", "image_version"):
        value = runner.get(field)
        if not isinstance(value, str) or not value:
            raise CollectionError(f"{source}: measurement.runner.{field} must be non-empty")

    results = document.get("results")
    if not isinstance(results, list) or not results:
        raise CollectionError(f"{source}: results must be a non-empty list")
    coordinates: set[tuple[str, str]] = set()
    for result in results:
        validate_result(result, source)
        coordinate = (result["configuration"], result["benchmark"])
        if coordinate in coordinates:
            raise CollectionError(f"{source}: duplicate result coordinate {coordinate!r}")
        coordinates.add(coordinate)

    summary = document.get("summary")
    expected_summary = {
        "successful_cases": sum(result["success"] for result in results),
        "total_cases": len(results),
    }
    if summary != expected_summary:
        raise CollectionError(f"{source}: summary does not match result rows")

    return document


def measurement_id(document: dict[str, Any]) -> str:
    workflow = document["workflow"]
    return ":".join(
        [
            workflow["repository"],
            str(workflow["run_id"]),
            str(workflow["run_attempt"]),
            workflow["artifact_name"],
        ]
    )


def commit_identity(document: dict[str, Any]) -> tuple[str, str]:
    upstream = document["upstream"]
    return upstream["repository"], upstream["commit"]


def workflow_run_identity(document: dict[str, Any]) -> tuple[str, int, int]:
    workflow = document["workflow"]
    return workflow["repository"], workflow["run_id"], workflow["run_attempt"]


def deduplicate_measurements_by_commit(
    measurements: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """Keep the earliest complete workflow run recorded for each upstream commit."""
    runs_by_commit: dict[
        tuple[str, str], dict[tuple[str, int, int], list[dict[str, Any]]]
    ] = {}
    try:
        for measurement in measurements:
            runs_by_commit.setdefault(commit_identity(measurement), {}).setdefault(
                workflow_run_identity(measurement), []
            ).append(measurement)
    except (KeyError, TypeError) as error:
        raise CollectionError("history measurement is missing commit or workflow identity") from error

    retained: list[dict[str, Any]] = []
    for runs in runs_by_commit.values():
        _, selected = min(
            runs.items(),
            key=lambda item: (
                min(record["measurement"]["timestamp"] for record in item[1]),
                item[0],
            ),
        )
        retained.extend(selected)

    retained.sort(key=lambda item: (item["measurement"]["timestamp"], item["id"]))
    return retained, len(measurements) - len(retained)


def read_history(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": 1, "generated_at": None, "measurements": []}
    try:
        history = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CollectionError(f"cannot read history {path}: {error}") from error
    if (
        not isinstance(history, dict)
        or history.get("schema_version") != 1
        or not isinstance(history.get("measurements"), list)
    ):
        raise CollectionError(f"{path}: unsupported history schema")
    return history


def csv_rows(history: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for measurement in history["measurements"]:
        workflow = measurement["workflow"]
        upstream = measurement["upstream"]
        details = measurement["measurement"]
        runner = details["runner"]
        common = {
            "measurement_id": measurement["id"],
            "measured_at": details["timestamp"],
            "workflow_repository": workflow["repository"],
            "run_id": workflow["run_id"],
            "run_attempt": workflow["run_attempt"],
            "run_url": workflow["run_url"],
            "upstream_repository": upstream["repository"],
            "upstream_ref": upstream["ref"],
            "upstream_commit": upstream["commit"],
            "commit_url": upstream["commit_url"],
            "ghc": details["ghc"],
            "example": details["example"],
            "runner_os": runner["os"],
            "runner_arch": runner["arch"],
            "runner_image": runner["image"],
            "runner_image_version": runner["image_version"],
        }
        for result in measurement["results"]:
            rows.append({**common, **{field: result[field] for field in RESULT_FIELDS}})
    return rows


def write_history(history: dict[str, Any], json_path: Path, csv_path: Path) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(history, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(csv_rows(history))


def collect(
    input_directory: Path,
    history_json: Path,
    history_csv: Path,
    *,
    expected_repository: str,
    expected_run_id: int,
    expected_run_attempt: int,
    expected_upstream_repository: str,
    expected_upstream_commit: str,
    expected_artifacts: int,
) -> tuple[int, int]:
    if expected_artifacts <= 0:
        raise CollectionError("expected artifact count must be greater than zero")
    manifests = sorted(input_directory.glob("observer-benchmark-*/benchmark.json"))
    if len(manifests) != expected_artifacts:
        raise CollectionError(
            f"expected {expected_artifacts} benchmark artifacts, found {len(manifests)}"
        )

    incoming = [
        validate_manifest(
            manifest,
            expected_repository=expected_repository,
            expected_run_id=expected_run_id,
            expected_run_attempt=expected_run_attempt,
            expected_upstream_repository=expected_upstream_repository,
            expected_upstream_commit=expected_upstream_commit,
        )
        for manifest in manifests
    ]
    incoming_ids = [measurement_id(document) for document in incoming]
    if len(set(incoming_ids)) != len(incoming_ids):
        raise CollectionError("download contains duplicate benchmark artifact identities")

    coordinates = {
        (document["measurement"]["ghc"], document["measurement"]["example"])
        for document in incoming
    }
    if len(coordinates) != len(incoming):
        raise CollectionError("download contains duplicate GHC/example matrix coordinates")

    history = read_history(history_json)
    history["measurements"], removed_duplicates = deduplicate_measurements_by_commit(
        history["measurements"]
    )
    existing_commits = {
        commit_identity(measurement) for measurement in history["measurements"]
    }
    incoming_commits = {commit_identity(document) for document in incoming}
    if len(incoming_commits) != 1:
        raise CollectionError("download contains multiple upstream commits")

    additions = 0
    incoming_commit = next(iter(incoming_commits))
    if incoming_commit not in existing_commits:
        for document, identity in zip(incoming, incoming_ids, strict=True):
            record = copy.deepcopy(document)
            record["id"] = identity
            history["measurements"].append(record)
            additions += 1

    if additions or removed_duplicates:
        history["measurements"].sort(
            key=lambda item: (item["measurement"]["timestamp"], item["id"])
        )
        history["generated_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        write_history(history, history_json, history_csv)

    return additions, len(history["measurements"])


def repository(value: str) -> str:
    if REPOSITORY.fullmatch(value) is None:
        raise argparse.ArgumentTypeError("repository must have OWNER/REPO form")
    return value


def commit(value: str) -> str:
    value = value.lower()
    if COMMIT.fullmatch(value) is None:
        raise argparse.ArgumentTypeError("commit must be a full 40-character SHA")
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--history-json", required=True, type=Path)
    parser.add_argument("--history-csv", required=True, type=Path)
    parser.add_argument("--expected-repository", required=True, type=repository)
    parser.add_argument("--expected-run-id", required=True, type=int)
    parser.add_argument("--expected-run-attempt", required=True, type=int)
    parser.add_argument("--expected-upstream-repository", required=True, type=repository)
    parser.add_argument("--expected-upstream-commit", required=True, type=commit)
    parser.add_argument("--expected-artifacts", required=True, type=int)
    args = parser.parse_args()

    added, total = collect(
        args.input,
        args.history_json,
        args.history_csv,
        expected_repository=args.expected_repository,
        expected_run_id=args.expected_run_id,
        expected_run_attempt=args.expected_run_attempt,
        expected_upstream_repository=args.expected_upstream_repository,
        expected_upstream_commit=args.expected_upstream_commit,
        expected_artifacts=args.expected_artifacts,
    )
    print(json.dumps({"added": added, "total": total}, sort_keys=True))


if __name__ == "__main__":
    main()
