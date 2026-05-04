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
