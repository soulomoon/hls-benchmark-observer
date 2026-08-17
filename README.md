# HLS benchmark observer

This repository is a self-contained HLS performance observer:

```text
upstream-benchmark-observer.yml
  -> resolve exact upstream SHA and skip commits already in history
  -> build and run the 4-coordinate benchmark matrix
  -> validate same-run artifacts and commit durable history
  -> pages.yml deploys the dashboard
```

The build jobs check out the requested commit from `haskell/haskell-language-server` and have read-only repository access. Only the final collection job receives `contents: write`; it runs after the complete benchmark matrix succeeds and validates every artifact before updating history. Every stored row carries the exact upstream commit, workflow run, runner image, GHC version, example, and success flag.

## One-time setup

1. Publish this directory as `soulomoon/hls-benchmark-observer`.
2. Enable GitHub Pages with **GitHub Actions** as the source.
3. Run **Upstream Benchmark Observer** manually once. Daily runs start at `18:17 UTC`; the non-zero minute avoids GitHub's busiest scheduling boundary.

No PAT or repository secret is required. The workflow uses its job-scoped `GITHUB_TOKEN`: benchmark jobs get `contents: read`, while the collector alone gets `contents: write` and `actions: write`. The collector checks the full SHA against every same-run artifact and requires the complete matrix. History identity is the exact upstream repository plus commit: the first complete matrix recorded for a commit wins, later runs of that commit are ignored, and the resolver skips them before allocating benchmark runners.

The dashboard includes an **All workloads (total)** workload. Its total-time value is the sum of every recorded workload for the selected project and GHC; pass coverage remains visible so a functional benchmark failure is not mistaken for a complete green run.

## Local checks

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile scripts/*.py tests/*.py
```

`data/history.json` is the dashboard's source of truth. `data/history.csv` is a deterministic flattened export for notebooks and external analysis. Actions artifacts are transient transport only.
