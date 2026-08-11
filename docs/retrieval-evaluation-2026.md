# Retrieval Evaluation Snapshot (2026-08-02)

## External-validity protocol update (2026-08-04)

The external evaluation gate is now implemented and has produced a pinned
CORE-Bench Level-2 selection manifest:
[`core-bench-level2-external-manifest.json`](core-bench-level2-external-manifest.json).
The separately pinned SWE-bench Verified component is recorded in
[`swebench-verified-external-manifest.json`](swebench-verified-external-manifest.json).

- source dataset revision: `23aee66caabfcd8fec37cb5518c96ae43069460a`;
- 200 real issue/query identifiers across 22 repositories;
- repository-disjoint train/dev/test: 122/28/50 cases over 13/4/5 repositories;
- frozen test partition with SHA-256 verification;
- external-validity audit: all 7 checks pass, including minimum size,
  repository disjointness, source provenance, no test-derived tuning, and
  frozen-test integrity.

SWE-bench Verified adds 500 human-validated issues from 12 Python repositories.
Gold patches yield 623 file-localization labels, split by repository into
365/129/129 train/dev/test cases over 7/2/3 repositories. Because the dataset
contains only 12 repositories, it is reported as a separate external component;
the 20-repository gate is satisfied by the CORE-Bench selection, not by
relaxing the threshold for SWE-bench Verified.

This closes the dataset-selection and leakage-control gap, but it is not a
retrieval result. The manifest intentionally contains identifiers and hashes,
not copied query text or corpus content. RQ1 remains unanswered until the
pinned corpus is downloaded and the baseline/full-method matrix is executed.

This is the versionable summary of the first retrieval-core upgrade. Raw local outputs are under `.tmp/retrieval-upgrade/`; the detailed local report is `reports/retrieval-upgrade-2026-08-02.md`.

## Reproducible commands

```powershell
python -m repo_agent benchmark-adapter --suite repo_agent/benchmark_adapter_suite.json --output .tmp/retrieval-upgrade/final-portable-optimized.json
python -m repo_agent benchmark-adapter --suite repo_agent/benchmark_challenge_suite.json --output .tmp/retrieval-upgrade/final-challenge-optimized.json
python -m pytest tests/test_retrieval.py tests/test_parsers.py tests/test_ranking_regressions.py tests/test_indexing.py -q
python -m mypy repo_agent
python -m ruff check repo_agent tests
```

## Results

| Suite / variant | Cases | Top-1 | Top-3 | MRR | Distractor@1 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Portable pre-upgrade workspace | 10 | 40.0% | 50.0% | 0.492 | 0.0% |
| Portable upgraded | 10 | 100.0% | 100.0% | 1.000 | 0.0% |
| Challenge upgraded | 32 | 84.375% | 93.750% | 0.880 | 0.0% |

Portable absolute improvement: Top-1 `+60.0 pp`, Top-3 `+50.0 pp`, MRR `+0.508`.

The optimized portable run completed in `8.10 s`; the challenge run completed in `86.46 s` on the local Windows/Anaconda environment with warm filesystem/cache state. These wall times are local diagnostics, not cross-machine claims.

Focused retrieval/parser/indexing regression tests pass `27/27`. Ruff passes for `repo_agent` and `tests`; mypy passes for all 30 source modules. The full 171-test suite exceeded a 180-second local time limit, so complete-suite performance remains open.

## Remaining challenge misses

- `express_public_chat_authorizer`: expected rank 2.
- `simple_agent_stream_turn_builder`: expected rank 3.
- `fastapi_admin_clear_state`: expected rank 3.
- `repo_web_run_history_refresh`: miss@6.
- `repo_config_package_data`: miss@6.

This snapshot proves a bundled-suite regression improvement, not superiority over external systems. External CORE-Bench/SWE-bench localization, matched BM25/dense/Zoekt baselines, ablations, confidence intervals, and downstream agent-success measurements are still required. The protocol is defined in `docs/retrieval-research-2026.md`.
