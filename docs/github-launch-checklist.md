# GitHub Launch Checklist

Use this checklist before publishing Repo Agent publicly.

## Repository metadata

- Repository name:
  `repo-agent`
- Suggested short description:
  `Evidence-first repository investigation and bug localization before AI edits code.`
- Suggested topics:
  `agent`, `code-search`, `bug-localization`, `bug-triage`, `repository-analysis`, `developer-tools`, `evidence`, `rag`, `llm`, `code-intelligence`

## Visual assets

- README demo image:
  [assets/studio-overview.svg](../assets/studio-overview.svg)
- Social preview image:
  [assets/social-preview.svg](../assets/social-preview.svg)

## Before first public push

- Remove generated files from `logs/`, `reports/`, and `.cache/`
- Remove generated files from `runs/` and `.tmp/`
- Check that `.env` is not committed
- Run:

```powershell
py -3 -m compileall repo_agent tests
py -3 -m repo_agent eval
py -3 -m pytest
node --check web/app.js
py -3 -m repo_agent serve
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
- 1 public roadmap link
- 3-5 "known limitations" bullets so the project feels honest

## First release notes

Suggested title:

`v0.1.0 - Evidence-first repository investigation`

Suggested bullets:

- Added graph-aware repository retrieval with semantic reranking
- Added ranked evidence, trace output, and HTML report export
- Added local web studio for bug triage before code edits
- Added built-in example repositories and CI-backed evals
- Added safety controls, audit logging, and optional OpenAI-compatible model support
- Added experimental workspace engineering runs for reviewed follow-up edits
