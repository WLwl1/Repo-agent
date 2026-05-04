# Positioning

Repo Agent is the evidence layer before code changes. It is designed to answer "where should I look, and why?" before a coding agent edits files.

## Compared With Coding Agents

| Tool type | Primary job | Repo Agent stance |
| --- | --- | --- |
| Full coding agents | Plan, edit, test, and iterate | Use after evidence is clear |
| Chat-based code assistants | Explain or modify selected context | Use Repo Agent to find that context |
| Search tools | Match text quickly | Add route, symbol, role, semantic, and graph evidence |
| Static analyzers | Enforce known rules | Investigate unfamiliar behavior and likely locations |

## What Repo Agent Should Be Best At

- bug and feature localization
- route-to-handler tracing
- unfamiliar repository onboarding
- evidence reports for review
- cheap deterministic triage before model spend

## What It Should Not Pretend To Be

- a replacement for a full IDE
- a complete autonomous engineer
- a security sandbox for untrusted code
- a benchmark winner without public, reproducible evaluations

