# Demo Transcript

This is the fastest reviewer path through Repo Agent.

## Command

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\demo_showcase.ps1
```

## Expected Console Summary

```text
Top-1: 100.00%
Top-3: 100.00%
Repair rules: 3 validated / 0 proposed
Implementation: 3 / 3 validated rules implemented
Compiler: compiled_noop_verified with 5 ablation toggles

Showcase reports written under reports\showcase.
Start with reports\showcase\benchmark-repair-workbench.md for the repair-to-ablation story.
```

## What To Open

Open `reports/showcase/benchmark-repair-workbench.md`.

If the full release pack is generated with `-FullReleasePack`, also open `reports/release-pack/artifact-provenance.md`.

The report should show:

- `5` patch candidates
- `5` review-applicable ablation patches
- `5` experiments
- source loci for repair reasons in `repo_agent/indexer.py`
- diff hunks that disable one repair reason at a time
- for the full pack, a complete claim-to-artifact provenance graph

## Talk Track

The concise explanation:

> The project converts benchmark traces into repair rules, verifies those rules against real reranker source anchors, compiles them into intervention IR, and generates one-rule ablation diffs so each repair reason can be falsified.

The longer explanation:

> This is not just a code-search agent. It is a reliability loop around codebase agents. Retrieval produces proof, proof is attacked by generated counterexamples, benchmark failures become repair rules, repair rules are verified against source, and the workbench generates ablation patches to test whether each repair actually carries value.

## Why This Matters

The important distinction is not that the benchmark is currently green. The important distinction is that the system preserves a falsifiable chain:

```text
benchmark case
-> retrieval trace
-> repair rule
-> source implementation anchor
-> compiled intervention
-> ablation patch
-> provenance edge
-> release gate
```

That chain is what turns the project from a demo into an auditable research artifact.

## Follow-Up Questions

If a reviewer asks whether this overfits the bundled suite:

> The portable benchmark adapter accepts external repo/question/expected-symbol JSON without changing Python code. The bundled suite is small by design so the evidence is inspectable, but the adapter, diagnostics, synthesis, and workbench are built to ingest additional cases.

If a reviewer asks whether the workbench silently patches code:

> No. It emits reviewable candidate diffs and validation commands. Promotion still requires rerunning synthesis, implementation verification, compiler, workbench, artifact review, and the release gate.

If a reviewer asks where multi-agent value appears:

> The multi-agent layer is not chat-style voting. It is an evidence court: role-specialized agents emit hashed claims and challenges, and an arbiter accepts only when proof replay, mutation testing, adversarial evidence, and temporal repair checks discharge the challenges.
