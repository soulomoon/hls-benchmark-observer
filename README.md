# HLS benchmark observer

This repository is the durable half of an event-driven HLS performance pipeline:

```text
schedule.yml
  -> soulomoon/haskell-language-server/upstream-benchmark-observer.yml
  -> exact upstream SHA + 4 benchmark artifacts
  -> repository_dispatch(benchmark-complete)
  -> collect.yml validates and commits history
  -> pages.yml deploys the dashboard
```

The scheduler only starts a measurement. Completion is signalled by Repo B, so collection never guesses whether a benchmark has finished. Every stored row carries the exact upstream commit, workflow run, runner image, GHC version, example, and success flag.

## One-time setup

1. Publish this directory as a repository (the suggested name is `soulomoon/hls-benchmark-observer`).
2. In this repository, create `BENCHMARK_TOKEN`, a fine-grained token scoped to `soulomoon/haskell-language-server` with **Actions: read and write**. It triggers the runner and downloads its artifacts.
3. Optionally set repository variables `BENCHMARK_REPOSITORY` (the default is `soulomoon/haskell-language-server`), `BENCHMARK_WORKFLOW_REF` (the default is `master`), and `EXPECTED_ARTIFACTS` (the fixed matrix default is `4`).
4. In `soulomoon/haskell-language-server`, create `OBSERVER_TOKEN`, a fine-grained token scoped to this observer repository with **Contents: write**. It creates the `repository_dispatch` event.
5. Enable GitHub Pages with **GitHub Actions** as the source.
6. Run **Schedule upstream benchmark** manually once. Daily runs start at `18:17 UTC`; the non-zero minute avoids GitHub's busiest scheduling boundary.

Both cross-repository tokens are deliberately narrow. The observer rejects dispatches from any repository other than `BENCHMARK_REPOSITORY`, requires a successful runner workflow, checks the full SHA against every artifact, and requires the complete matrix. History identity is the exact upstream repository plus commit: the first complete matrix recorded for a commit wins, later runs of that commit are ignored, and the scheduler skips them before dispatch whenever possible.

The dashboard includes an **All workloads (total)** workload. Its total-time value is the sum of every recorded workload for the selected project and GHC; pass coverage remains visible so a functional benchmark failure is not mistaken for a complete green run.

## Local checks

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile scripts/collect.py tests/test_collect.py
```

`data/history.json` is the dashboard's source of truth. `data/history.csv` is a deterministic flattened export for notebooks and external analysis. Actions artifacts are transient transport only.
