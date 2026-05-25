# Repo Agent

Language:

- en [English](../README.md)
- zh_CN [简体中文](README.zh_CN.md)
- ja [日本語](README.ja.md)

Evidence-first repository investigation and bug localization before an AI edits code.

## Why Repo Agent

Most coding agents optimize for changing files. That is useful after you trust the context, but it is often too heavy, too expensive, and too opaque when the real first question is:

> Where should I look, and what is the evidence?

Repo Agent is a local codebase investigator. It focuses on proving the location of a bug, feature, route, handler, or execution path before asking a model to edit anything:

- parse real source code into symbols and file chunks
- build a lightweight repository graph from routes, handlers, decorators, imports, and calls
- retrieve grounded evidence with lexical recall, semantic projection, and graph expansion
- inspect the real workspace with directory listing, text search, file reads, and optional verification commands
- answer repository questions and bug-localization prompts with ranked evidence, line references, and trace output
- score each answer with evidence diagnostics: confidence, coverage, score gap, graph support, strengths, and warnings
- export a shareable HTML report for debugging, onboarding, and review
- export a portable evidence bundle for handoff to Codex, Aider, OpenHands, or another coding agent
- optionally hand the evidence to an OpenAI-compatible tool-calling loop when a model is configured

Repo Agent is not trying to be a clone of a full IDE coding agent. Its sharp edge is the step before coding: cheap local triage, inspectable evidence, and a report you can review with a human.

## Trust Signals

- Runs without an API key for deterministic, graph-aware retrieval
- Ships fixture repositories and CI-backed ranking metrics
- Ignores generated caches, logs, reports, and run workspaces during indexing
- Uses path validation for repository access and report/static-file serving
- Runs verification commands with `shell=False` and an allow-listed command shape
- Includes pytest coverage for parser, indexing, cache, security, and web-asset behavior

## Positioning

Repo Agent is the evidence layer before code changes. It pairs well with tools such as Aider, OpenHands, SWE-agent, or Codex: use Repo Agent to find the files, handlers, routes, traces, and confidence signals; then hand the evidence to a coding agent when you actually want edits.

It should be judged on localization quality, traceability, and reviewability rather than on how aggressively it changes files. See [docs/comparison.md](../docs/comparison.md) for a more explicit comparison.

## Key Capabilities

- Evidence-first repository QA and bug triage
- Ranked file, symbol, and line-level evidence
- Evidence confidence diagnostics that make retrieval quality and risk visible
- Express/FastAPI/Flask-style route and handler linking
- Multi-step repository investigation: plan -> file scout -> code read -> graph hop -> answer
- Trace output that shows how the result was found
- Shareable HTML reports for review and debugging
- Portable Markdown/JSON evidence bundles for downstream coding agents
- Model-optional workflow: deterministic retrieval works without an API key
- Real agent mode with model-selected tools: `repo_brief`, `find_relevant_code`, `list_directory`, `search_text`, `read_file`, `startup_hints`, and `verify_project`
- Local web studio for interactive analysis
- Workspace tool panel for directory listing, file reads, text search, startup hints, and allow-listed verification commands
- Experimental engineering mode with inspect -> edit -> verify -> repair -> finish loops
- Workspace sandbox mode that edits `runs/<run_id>/workspace` instead of the source repository
- Persistent run records under `runs/<run_id>/run.json`, including tool calls, changed files, verification output, and diff snapshots
- Built-in example repositories for reproducible demos
- CI-backed evals with Top-1, Top-3, and MRR metrics
- Safety controls for path validation, input limits, and index limits
- Centralized verification command policy that blocks arbitrary `python -c`, `node -e`, package-install, and traversal-shaped commands
- Audit logs for indexing, ask, map, report, and request failures

## When To Use It

Use Repo Agent when you need to:

- onboard into an unfamiliar repository
- find the route, handler, or execution path behind a behavior
- localize a likely bug before opening an editor
- produce a reviewable evidence trail for a teammate
- run cheap deterministic codebase search before spending model tokens

Use a full coding agent after you have enough evidence and want autonomous edits.

## Demo Questions

Try Repo Agent on the included fixture repos:

- `Where is the chat endpoint implemented?`
- `What should I inspect first for a streaming bug?`
- `Where does the RAG upload flow enter the codebase?`
- `What is the main execution path for this service?`
- `Can you quickly verify whether this project still runs?`

## Quick Start

### Install

```powershell
cd repo-agent
python -m pip install -e ".[dev]"
```

Once published, the target install shape is:

```powershell
pipx install repo-agent
```

### Run the built-in eval

```powershell
python -m repo_agent eval
```

### Ask a question from the CLI

```powershell
python -m repo_agent ask --repo ".\examples\simple_agent_app" --question "Where is the chat endpoint implemented?"
```

### Launch the web studio

```powershell
python -m repo_agent serve
```

Then open `http://127.0.0.1:8787`.

## Real AI Agent Mode

Repo Agent works without a model by default.

If you want the real agent loop, copy `.env.example` to `.env` and set:

- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`
- `OPENAI_MODEL`

Then run:

```powershell
python -m repo_agent ask --repo ".\examples\simple_agent_app" --question "Where is the chat endpoint implemented?" --use-model
```

With `--use-model`, Repo Agent gives the model a safe tool belt and records every tool call in the trace. The model can inspect files, search text, retrieve relevant code, ask for startup hints, and run allow-listed verification commands before producing the final answer.

Without `--use-model`, Repo Agent falls back to deterministic graph-aware retrieval and evidence ranking.

## Experimental Engineering Mode

Repo Agent includes an experimental engineering loop for small, controlled changes after investigation. It can inspect files, edit in a workspace copy, run allow-listed verification commands, and persist a full run record.

Prefer `--execution-mode workspace` so edits happen under `runs/<run_id>/workspace` first:

```powershell
python -m repo_agent engineer --repo ".\examples\simple_agent_app" --task "Add a small health endpoint" --execution-mode workspace
```

Run directly against the source repository only when you have reviewed the task and trust the edit surface:

```powershell
python -m repo_agent engineer --repo ".\examples\simple_agent_app" --task "Add a small health endpoint and verify the project still compiles" --execution-mode local
```

Resume a saved run:

```powershell
python -m repo_agent resume --run-id run_YYYYMMDD_HHMMSS_xxxxxxxx
```

Apply a reviewed workspace run back to the source repository:

```powershell
python -m repo_agent apply-run --run-id run_YYYYMMDD_HHMMSS_xxxxxxxx --confirm
```

Run engineering benchmark cases:

```powershell
python -m repo_agent bench --json
```

## Web Studio

The web studio supports repository path input, AI agent mode, autonomous engineering, workspace-sandbox execution, run history, one-click indexing, repository QA, startup hints, safe workspace tools, ranked evidence, traces, and HTML report preview.

## CLI Commands

```text
repo-agent index  --repo <path> [--force-rebuild]
repo-agent ask    --repo <path> --question "<query>" [--use-model] [--top-k <n>]
repo-agent engineer --repo <path> --task "<task>" [--execution-mode local|workspace] [--max-steps <n>] [--json]
repo-agent resume --run-id <run_id> [--max-steps <n>] [--json]
repo-agent runs [--limit <n>] [--json]
repo-agent apply-run --run-id <run_id> --confirm [--json]
repo-agent bench [--cases <path>] [--max-steps <n>] [--json]
repo-agent map    --repo <path> [--force-rebuild]
repo-agent report --repo <path> --question "<query>" [--use-model]
repo-agent bundle --repo <path> --question "<query>" [--target generic|codex|aider|openhands] [--format markdown|json]
repo-agent serve  [--host 127.0.0.1] [--port 8787]
repo-agent eval   [--top-k <n>] [--json]
```

## Evidence Bundles

Use `repo-agent bundle` when you want Repo Agent to do the investigation phase, then hand the grounded evidence to a coding agent for edits:

```powershell
python -m repo_agent bundle --repo ".\examples\simple_agent_app" --question "Where is the chat endpoint implemented?" --target codex
```

The bundle includes the repository brief, ranked evidence, snippets, graph edges, trace steps, evidence diagnostics, and a handoff prompt tailored to the selected target.

## Evaluation

Repo Agent ships with reproducible fixture repositories under `examples/`, so `repo-agent eval` works out of the box on a fresh clone and in CI.

```text
Summary: 11/11 passed @top3
Top-1 accuracy: 81.82%
Top-3 accuracy: 100.00%
MRR: 0.894
```

The built-in eval is a smoke suite, not a claim of broad benchmark dominance. The public benchmark plan is tracked in [docs/benchmarking.md](../docs/benchmarking.md).

## Quality Gate

```powershell
python -m compileall repo_agent tests
node --check web/app.js
python -m repo_agent eval
python -m pytest
```

## Configuration

See [`.env.example`](../.env.example) for optional model settings, allowed repository roots, question length limits, top-k limits, and index limits.

## Before Publishing

```powershell
pwsh .\scripts\clean_generated.ps1
```

For repository metadata, topics, and social preview suggestions, see:

- [docs/github-launch-checklist.md](../docs/github-launch-checklist.md)
- [docs/repository-metadata.md](../docs/repository-metadata.md)
- [docs/benchmarking.md](../docs/benchmarking.md)
- [docs/roadmap.md](../docs/roadmap.md)

## Contributing

See [CONTRIBUTING.md](../CONTRIBUTING.md).

For security-sensitive issues, see [SECURITY.md](../SECURITY.md).

## License

[MIT](../LICENSE)
