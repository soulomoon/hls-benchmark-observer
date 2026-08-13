from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from collect import CollectionError, collect  # noqa: E402


BENCHMARK_REPOSITORY = "soulomoon/haskell-language-server"
UPSTREAM_REPOSITORY = "haskell/haskell-language-server"
UPSTREAM_COMMIT = "a" * 40


def manifest(artifact: str, ghc: str, example: str) -> dict:
    return {
        "schema_version": 1,
        "upstream": {
            "repository": UPSTREAM_REPOSITORY,
            "ref": "master",
            "commit": UPSTREAM_COMMIT,
            "commit_url": f"https://github.com/{UPSTREAM_REPOSITORY}/commit/{UPSTREAM_COMMIT}",
        },
        "workflow": {
            "repository": BENCHMARK_REPOSITORY,
            "run_id": 123,
            "run_attempt": 1,
            "run_url": f"https://github.com/{BENCHMARK_REPOSITORY}/actions/runs/123",
            "artifact_name": artifact,
        },
        "measurement": {
            "timestamp": "2026-08-13T04:00:00Z",
            "ghc": ghc,
            "example": example,
            "runner": {
                "os": "Linux",
                "arch": "X64",
                "image": "ubuntu24",
                "image_version": "20260801.1",
            },
        },
        "summary": {"successful_cases": 1, "total_cases": 1},
        "results": [
            {
                "version": "HEAD",
                "configuration": "All",
                "benchmark": "hover",
                "success": True,
                "samples": 50,
                "startup_ms": 700.0,
                "setup_ms": 1.0,
                "user_time_ms": 2.0,
                "delayed_time_ms": 3.0,
                "first_build_ms": 4.0,
                "average_response_ms": 5.0,
                "total_time_ms": 6.0,
                "rules_built": 1,
                "rules_changed": 2,
                "rules_visited": 3,
                "rules_total": 4,
                "rule_edges": 5,
                "ghc_rebuilds": 6,
                "max_residency_mb": 421.0,
                "allocated_mb": 900.0,
            }
        ],
    }


class CollectTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.incoming = self.root / "incoming"
        self.history_json = self.root / "data" / "history.json"
        self.history_csv = self.root / "data" / "history.csv"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write_manifest(self, artifact: str, ghc: str, example: str) -> Path:
        target = self.incoming / artifact / "benchmark.json"
        target.parent.mkdir(parents=True)
        target.write_text(json.dumps(manifest(artifact, ghc, example)), encoding="utf-8")
        return target

    def run_collect(self, expected_artifacts: int = 2) -> tuple[int, int]:
        return collect(
            self.incoming,
            self.history_json,
            self.history_csv,
            expected_repository=BENCHMARK_REPOSITORY,
            expected_run_id=123,
            expected_run_attempt=1,
            expected_upstream_repository=UPSTREAM_REPOSITORY,
            expected_upstream_commit=UPSTREAM_COMMIT,
            expected_artifacts=expected_artifacts,
        )

    def test_appends_complete_matrix_and_is_idempotent(self) -> None:
        self.write_manifest("observer-benchmark-cabal-ghc-9.14", "9.14", "cabal")
        self.write_manifest("observer-benchmark-lsp-types-ghc-9.14", "9.14", "lsp-types")

        self.assertEqual(self.run_collect(), (2, 2))
        original_json = self.history_json.read_bytes()
        original_csv = self.history_csv.read_bytes()
        self.assertEqual(self.run_collect(), (0, 2))
        self.assertEqual(self.history_json.read_bytes(), original_json)
        self.assertEqual(self.history_csv.read_bytes(), original_csv)
        self.assertEqual(len(self.history_csv.read_text(encoding="utf-8").splitlines()), 3)

    def test_rejects_incomplete_artifact_set(self) -> None:
        self.write_manifest("observer-benchmark-cabal-ghc-9.14", "9.14", "cabal")
        with self.assertRaisesRegex(CollectionError, "expected 2.*found 1"):
            self.run_collect()

    def test_rejects_payload_artifact_commit_mismatch(self) -> None:
        path = self.write_manifest("observer-benchmark-cabal-ghc-9.14", "9.14", "cabal")
        document = json.loads(path.read_text(encoding="utf-8"))
        document["upstream"]["commit"] = "b" * 40
        path.write_text(json.dumps(document), encoding="utf-8")
        with self.assertRaisesRegex(CollectionError, "upstream.commit"):
            self.run_collect(expected_artifacts=1)

    def test_rejects_duplicate_result_coordinate(self) -> None:
        path = self.write_manifest("observer-benchmark-cabal-ghc-9.14", "9.14", "cabal")
        document = json.loads(path.read_text(encoding="utf-8"))
        document["results"].append(document["results"][0].copy())
        document["summary"] = {"successful_cases": 2, "total_cases": 2}
        path.write_text(json.dumps(document), encoding="utf-8")
        with self.assertRaisesRegex(CollectionError, "duplicate result coordinate"):
            self.run_collect(expected_artifacts=1)

    def test_rejects_inaccurate_summary(self) -> None:
        path = self.write_manifest("observer-benchmark-cabal-ghc-9.14", "9.14", "cabal")
        document = json.loads(path.read_text(encoding="utf-8"))
        document["summary"]["successful_cases"] = 0
        path.write_text(json.dumps(document), encoding="utf-8")
        with self.assertRaisesRegex(CollectionError, "summary does not match"):
            self.run_collect(expected_artifacts=1)

    def test_rejects_non_finite_metric(self) -> None:
        path = self.write_manifest("observer-benchmark-cabal-ghc-9.14", "9.14", "cabal")
        document = json.loads(path.read_text(encoding="utf-8"))
        document["results"][0]["startup_ms"] = float("inf")
        path.write_text(json.dumps(document), encoding="utf-8")
        with self.assertRaisesRegex(CollectionError, "finite non-negative"):
            self.run_collect(expected_artifacts=1)


if __name__ == "__main__":
    unittest.main()
