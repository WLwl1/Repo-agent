# Benchmarking

Repo Agent should be judged on whether it finds the right code location with enough evidence for a human to trust the next step.

## Built-In Retrieval Eval

Run:

```powershell
python -m repo_agent eval --json
```

The bundled fixture suite reports:

- Top-1 accuracy
- Top-3 accuracy
- MRR
- per-question rank and top hits

The fixture suite is intentionally small and fast enough for CI. It protects basic route, handler, frontend, and RAG localization behavior.

## Portable Generalization Suite

Run:

```powershell
python -m repo_agent benchmark-adapter --suite repo_agent/benchmark_adapter_suite.json --output reports/benchmark-adapter.json --json
python -m repo_agent benchmark-diagnose --benchmark reports/benchmark-adapter.json --output reports/benchmark-diagnostics.md
```

The bundled core portable suite is the release-pack bridge between the tiny CI eval and external benchmarks. It remains small and stable enough for reproducible release artifacts while covering Express, FastAPI, RAG, frontend browser logic, route-grounded call chains, and hard-negative distractors.

For harder research pressure, run the challenge suite:

```powershell
python -m repo_agent benchmark-adapter --suite repo_agent/benchmark_challenge_suite.json --output reports/benchmark-challenge.json --json
python -m repo_agent benchmark-diagnose --benchmark reports/benchmark-challenge.json --output reports/benchmark-challenge-diagnostics.md
```

The challenge suite includes 32+ repository-localization tasks across Express, FastAPI, RAG, frontend browser logic, packaging config, security policy, safety regression tests, API actions, route-grounded call chains, state reset flows, and hard-negative distractors. It is allowed to return `needs_attention`; that result is useful because it identifies generalization gaps that should drive retrieval repair work.

The suite is intentionally stored as JSON so reviewers can add third-party tasks without changing Python code. Each case should include a repository path, natural-language question, expected file path, optional expected symbol substring, optional distractor symbols, and tags.

Quality gates:

- `tests/test_benchmark_suite.py` verifies core-suite release stability plus challenge-suite case id uniqueness, fixture path validity, minimum suite size, repo diversity, security/safety/API tag coverage, and hard-negative coverage.
- `repo_agent.benchmark_suite.audit_benchmark_suite` exposes those checks as a reusable machine-readable audit payload, with Markdown rendering for reviewer packets.
- `benchmark-adapter` reports Top-1, Top-3, MRR, distractor@1, confidence, per-repo metrics, per-tag metrics, top-hit reasons, and stable evidence hashes.
- `benchmark-diagnose` turns weak groups into repair ceilings and action items, so misses are useful rather than hidden.

## Engineering Benchmark

Run:

```powershell
python -m repo_agent bench --json
```

Engineering cases require a configured model. If `OPENAI_API_KEY`, `OPENAI_BASE_URL`, and `OPENAI_MODEL` are missing, cases are marked as skipped instead of counted as failed.

Because these cases can spend model tokens and depend on network/service availability, they are opt-in:

```powershell
$env:REPO_AGENT_RUN_ENGINEERING_BENCHMARKS = "1"
python -m repo_agent bench --json
```

## Public Benchmark Roadmap

The next benchmark tier should include 50-100 real-world localization tasks across:

- Python web services
- Node/Express services
- React or static frontend projects
- mixed backend/frontend issue trails
- config and test discovery tasks

Each case should define:

- repository URL or fixture path
- natural-language question
- accepted file path
- optional accepted symbol substring
- expected evidence type, such as route, handler, call edge, or config file

## Reporting Results

Publish benchmark results with both wins and misses. A useful report includes:

- dataset version
- Repo Agent version or commit
- command line used
- Top-1, Top-3, and MRR
- at least five representative failures
- runtime and machine details when comparing tools
