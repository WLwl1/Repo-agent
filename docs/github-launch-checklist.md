# GitHub Launch Checklist

Use this checklist before publishing Repo Agent publicly.

## Repository metadata

- Repository name:
  `repo-agent`
- Suggested short description:
  `Proof-carrying codebase investigation and benchmark-driven repair before AI edits code.`
- Suggested topics:
  `agent`, `code-search`, `bug-localization`, `repository-analysis`, `developer-tools`, `proof`, `benchmarking`, `rag`, `llm`, `code-intelligence`

## Visual assets

- README demo image:
  [assets/repo-agent-paper-method-figure-v4.png](../assets/repo-agent-paper-method-figure-v4.png)
- Social preview image:
  [assets/social-preview.svg](../assets/social-preview.svg)

## Before first public push

- Remove generated files from `logs/`, `reports/`, and `.cache/`
- Remove generated files from `runs/` and `.tmp/`
- Check that `.env` is not committed
- Run:

```powershell
python -m compileall repo_agent tests examples
node --check web/app.js
python -m pytest
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\demo_showcase.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\release_gate.ps1
```

- Verify the README renders correctly on GitHub
- Add repository topics and social preview image in GitHub settings

## Good first launch content

- 1 short GIF or screen recording of:
  - asking "where should I look?" before editing code
  - opening ranked evidence
  - inspecting the trace
  - exporting an HTML report
- 1 architecture figure
- 1 benchmark snippet from the built-in eval
- 1 benchmark repair workbench snippet showing generated ablation diffs
- 1 artifact review snippet showing `9/9` supported claims and `80/80` verified artifacts
- 1 artifact provenance snippet showing complete claim-to-metric/artifact/command/falsifier edges
- 1 public roadmap link
- 3-5 "known limitations" bullets so the project feels honest

## First release notes

Suggested title:

`v0.1.0 - Proof-carrying repository investigation`

Suggested bullets:

- Added graph-aware repository retrieval with semantic reranking
- Added proof-carrying evidence bundles with strict replay and mutation tests
- Added generated proof attacks, adaptive policy repair, and minimax certificates
- Added portable benchmark adapter, repair synthesis, implementation verification, compiler, and patch workbench
- Added release-pack manifest with tamper-evident artifact hashes
- Added artifact evaluation card with falsifiers, validation commands, limitations, and reviewer protocol
- Added artifact provenance graph linking claims to metrics, artifact hashes, validation commands, and falsifiers
