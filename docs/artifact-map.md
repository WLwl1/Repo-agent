# Artifact Map

This map explains which artifacts to open, what each artifact proves, and why it matters in an interview or project review.

## Fast Path

| Artifact | Open When | What It Proves |
| --- | --- | --- |
| `reports/showcase/benchmark-repair-workbench.md` | You want the fastest technical demo. | Benchmark failures become repair rules, source anchors, ablation diffs, experiments, and validation commands. |
| `reports/release-pack/agent-artifact-review.md` | You want reviewer-facing evidence. | Major project claims are tied to artifacts, metrics, falsifiers, limitations, and validation commands. |
| `reports/release-pack/artifact-provenance.md` | You want a machine-checkable evidence graph. | Claims are connected to metrics, artifact hashes, validation commands, and falsifier conditions. |
| `reports/release-pack/manifest.json` | You want integrity evidence. | Release-pack artifacts are hash-tracked so missing or tampered outputs can be detected. |
| `reports/release-pack/proof-attack-certificate.md` | You want the adversarial research loop. | Proof-carrying retrieval is attacked, repaired, and certified through baseline and adaptive counterexamples. |
| `reports/release-pack/agent-frontier-stability.md` | You want the multi-agent frontier story. | Reliability dimensions are stress-tested with bootstrap perturbations and Pareto survival analysis. |

## Evidence Chain

```text
question or benchmark case
-> ranked retrieval trace
-> proof-carrying evidence
-> adversarial or benchmark counterexample
-> repair rule synthesis
-> implementation verification
-> compiled intervention IR
-> reviewable ablation patch
-> artifact review card
-> claim-to-artifact provenance graph
-> release gate
```

## Interview Reading Order

1. Start with [docs/github-showcase.md](github-showcase.md) for the narrative.
2. Run `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\demo_showcase.ps1`.
3. Open `reports/showcase/benchmark-repair-workbench.md`.
4. Run `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\release_gate.ps1`.
5. Open `reports/release-pack/agent-artifact-review.md`, `reports/release-pack/artifact-provenance.md`, and `reports/release-pack/manifest.json`.

## Why These Artifacts Matter

The core value is not a single high benchmark score. The stronger claim is that Repo Agent preserves a falsifiable trail from a repository question to source-level evidence and then to repair experiments.

That is the part worth emphasizing in interviews:

- The system is local and inspectable before model-driven edits happen.
- It uses graph search, proof replay, mutation tests, and adversarial counterexamples to expose retrieval risk.
- It turns benchmark weaknesses into repair rules that must be verified against real source anchors.
- It locks intent-guard repairs with challenge cases for authorization, sync JSON, clear-state, package config, verification policy, and run-apply actions.
- It compiles repairs into ablation-ready patches instead of relying on narrative claims.
- It packages the resulting claims into a hash-verified release pack.
- It exports a claim-to-artifact provenance graph so reviewers can audit which metrics, commands, artifacts, and falsifiers support each claim.

## What To Say In 30 Seconds

> Repo Agent is a reliability layer for codebase agents. It finds code with graph-aware retrieval, attaches replayable proof, attacks that proof with generated counterexamples, converts benchmark failures into repair rules, verifies those rules against source, and emits ablation patches so each repair can be tested instead of trusted.
