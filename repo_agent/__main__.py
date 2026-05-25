from __future__ import annotations

import argparse
import json
from pathlib import Path

from .benchmarks import run_engineering_benchmark
from .runtime import RepoAgentRuntime
from .security import clamp_top_k
from .server import serve


def main() -> None:
    project_root = Path(__file__).resolve().parent.parent
    runtime = RepoAgentRuntime(project_root)

    parser = argparse.ArgumentParser(description="Repo Agent CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    index_parser = subparsers.add_parser("index", help="Inspect a repository and print index stats.")
    index_parser.add_argument("--repo", required=True, help="Path to the target repository.")
    index_parser.add_argument("--force-rebuild", action="store_true", help="Ignore cache and rebuild the index.")

    ask_parser = subparsers.add_parser("ask", help="Ask a repository question.")
    ask_parser.add_argument("--repo", required=True, help="Path to the target repository.")
    ask_parser.add_argument("--question", required=True, help="Question for the agent.")
    ask_parser.add_argument("--top-k", type=int, default=6, help="How many hits to retrieve.")
    ask_parser.add_argument("--use-model", action="store_true", help="Use an OpenAI-compatible model if configured.")
    ask_parser.add_argument("--force-rebuild", action="store_true", help="Ignore cache and rebuild the index.")

    map_parser = subparsers.add_parser("map", help="Print a repository overview.")
    map_parser.add_argument("--repo", required=True, help="Path to the target repository.")
    map_parser.add_argument("--force-rebuild", action="store_true", help="Ignore cache and rebuild the index.")

    report_parser = subparsers.add_parser("report", help="Generate a visual HTML investigation report.")
    report_parser.add_argument("--repo", required=True, help="Path to the target repository.")
    report_parser.add_argument("--question", required=True, help="Question for the agent.")
    report_parser.add_argument("--output", help="Optional output HTML path.")
    report_parser.add_argument("--top-k", type=int, default=6, help="How many hits to retrieve.")
    report_parser.add_argument("--use-model", action="store_true", help="Use an OpenAI-compatible model if configured.")
    report_parser.add_argument("--force-rebuild", action="store_true", help="Ignore cache and rebuild the index.")

    bundle_parser = subparsers.add_parser("bundle", help="Export a portable evidence bundle for another coding agent.")
    bundle_parser.add_argument("--repo", required=True, help="Path to the target repository.")
    bundle_parser.add_argument("--question", required=True, help="Question for the agent.")
    bundle_parser.add_argument(
        "--target",
        choices=("generic", "codex", "aider", "openhands"),
        default="generic",
        help="Downstream agent or handoff target.",
    )
    bundle_parser.add_argument(
        "--format",
        choices=("markdown", "json"),
        default="markdown",
        help="Evidence bundle output format.",
    )
    bundle_parser.add_argument("--output", help="Optional output path.")
    bundle_parser.add_argument("--top-k", type=int, default=6, help="How many hits to retrieve.")
    bundle_parser.add_argument("--use-model", action="store_true", help="Use an OpenAI-compatible model if configured.")
    bundle_parser.add_argument("--force-rebuild", action="store_true", help="Ignore cache and rebuild the index.")

    engineer_parser = subparsers.add_parser("engineer", help="Run an autonomous software engineering task.")
    engineer_parser.add_argument("--repo", required=True, help="Path to the target repository.")
    engineer_parser.add_argument("--task", required=True, help="Engineering task for the autonomous agent.")
    engineer_parser.add_argument("--max-steps", type=int, default=6, help="Maximum autonomous model/tool turns.")
    engineer_parser.add_argument(
        "--execution-mode",
        choices=("local", "workspace"),
        default="workspace",
        help="Edit the source repo directly or an isolated runs/<id>/workspace copy.",
    )
    engineer_parser.add_argument("--force-rebuild", action="store_true", help="Ignore cache and rebuild the index.")
    engineer_parser.add_argument("--json", action="store_true", help="Print machine-readable run data.")

    resume_parser = subparsers.add_parser("resume", help="Resume a persisted autonomous engineering run.")
    resume_parser.add_argument("--run-id", required=True, help="Run id from runs/<run_id>.")
    resume_parser.add_argument("--max-steps", type=int, default=6, help="Additional autonomous model/tool turns.")
    resume_parser.add_argument("--json", action="store_true", help="Print machine-readable run data.")

    runs_parser = subparsers.add_parser("runs", help="List recent autonomous engineering runs.")
    runs_parser.add_argument("--limit", type=int, default=20, help="Maximum runs to print.")
    runs_parser.add_argument("--json", action="store_true", help="Print machine-readable run data.")

    apply_parser = subparsers.add_parser("apply-run", help="Apply a workspace run's changed files to the source repo.")
    apply_parser.add_argument("--run-id", required=True, help="Run id from runs/<run_id>.")
    apply_parser.add_argument("--confirm", action="store_true", help="Required to apply files to the source repository.")
    apply_parser.add_argument("--json", action="store_true", help="Print machine-readable apply result.")

    bench_parser = subparsers.add_parser("bench", help="Run autonomous engineering benchmark cases.")
    bench_parser.add_argument(
        "--cases",
        default=str(Path(__file__).with_name("engineering_cases.json")),
        help="Path to engineering benchmark case JSON.",
    )
    bench_parser.add_argument("--max-steps", type=int, default=6, help="Default maximum steps per case.")
    bench_parser.add_argument("--json", action="store_true", help="Print machine-readable benchmark data.")

    serve_parser = subparsers.add_parser("serve", help="Launch the local web studio.")
    serve_parser.add_argument("--host", default="127.0.0.1", help="Host address.")
    serve_parser.add_argument("--port", type=int, default=8787, help="Server port.")

    eval_parser = subparsers.add_parser("eval", help="Run bundled evaluation cases.")
    eval_parser.add_argument(
        "--cases",
        default=str(Path(__file__).with_name("eval_cases.json")),
        help="Path to evaluation case JSON.",
    )
    eval_parser.add_argument("--top-k", type=int, default=6, help="How many hits to retrieve for each case.")
    eval_parser.add_argument("--json", action="store_true", help="Print machine-readable evaluation metrics.")

    args = parser.parse_args()

    if args.command == "index":
        repo_index = runtime.load_index(args.repo, force_rebuild=args.force_rebuild)
        print(json.dumps(repo_index.stats(), ensure_ascii=False, indent=2))
        return

    if args.command == "ask":
        result, _repo_index = runtime.ask(
            repo_path=args.repo,
            question=args.question,
            top_k=clamp_top_k(args.top_k, runtime.config),
            use_model=args.use_model,
            force_rebuild=args.force_rebuild,
        )
        print(result.answer)
        if result.diagnostics:
            print("\n[Confidence]")
            print(f"- {result.diagnostics.label} ({result.diagnostics.confidence:.2f})")
            for warning in result.diagnostics.warnings[:3]:
                print(f"- warning: {warning}")
        print("\n[Top Hits]")
        for hit in result.hits:
            print(
                f"- {hit.chunk.source_label} "
                f"({hit.chunk.start_line}-{hit.chunk.end_line}) "
                f"score={hit.score:.2f}"
            )
        if result.model_name:
            print(f"\n[Model]\n- {result.model_name}")
        return

    if args.command == "map":
        repo_index = runtime.load_index(args.repo, force_rebuild=args.force_rebuild)
        print(json.dumps(repo_index.repository_overview(), ensure_ascii=False, indent=2))
        return

    if args.command == "report":
        result, _repo_index, report_path = runtime.generate_report(
            repo_path=args.repo,
            question=args.question,
            top_k=clamp_top_k(args.top_k, runtime.config),
            use_model=args.use_model,
            force_rebuild=args.force_rebuild,
            output_path=args.output,
        )
        print(str(report_path))
        if result.model_name:
            print(f"model={result.model_name}")
        return

    if args.command == "bundle":
        bundle, bundle_path = runtime.generate_bundle(
            repo_path=args.repo,
            question=args.question,
            target=args.target,
            fmt=args.format,
            top_k=clamp_top_k(args.top_k, runtime.config),
            use_model=args.use_model,
            force_rebuild=args.force_rebuild,
            output_path=args.output,
        )
        print(str(bundle_path))
        print(f"target={bundle.get('target', '')}")
        print(f"evidence={len(bundle.get('evidence', []))}")
        return

    if args.command == "engineer":
        result, _repo_index = runtime.engineer(
            repo_path=args.repo,
            task=args.task,
            max_steps=args.max_steps,
            execution_mode=args.execution_mode,
            force_rebuild=args.force_rebuild,
        )
        _print_engineering_result(result, json_output=args.json)
        return

    if args.command == "resume":
        result, _repo_index = runtime.resume_engineering_run(args.run_id, max_steps=args.max_steps)
        _print_engineering_result(result, json_output=args.json)
        return

    if args.command == "runs":
        runs = runtime.list_engineering_runs(limit=args.limit)
        if args.json:
            print(json.dumps({"runs": runs}, ensure_ascii=False, indent=2))
            return
        for item in runs:
            print(f"- {item.get('run_id')} | {item.get('status')} | {item.get('task')}")
        return

    if args.command == "apply-run":
        result = runtime.apply_engineering_run(args.run_id, confirm=args.confirm)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return
        print(f"Applied run {result.get('run_id')} to {result.get('source_repo_root')}")
        for relpath in result.get("applied_files", []):
            print(f"- {relpath}")
        return

    if args.command == "bench":
        result = run_engineering_benchmark(runtime, Path(args.cases), max_steps=args.max_steps)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return
        runnable = result.get("runnable_count", result["case_count"])
        skipped = result.get("skipped_count", 0)
        print(
            f"Engineering benchmark: {result['case_count']} cases, "
            f"{runnable} runnable, {skipped} skipped, pass rate {result['pass_rate']:.2%}"
        )
        for item in result["cases"]:
            status = "SKIP" if item.get("skipped") else ("PASS" if item["passed"] else "FAIL")
            print(f"- [{status}] {item['name']} -> {item['status']} ({item['run_id']})")
        return

    if args.command == "serve":
        serve(project_root=project_root, host=args.host, port=args.port)
        return

    if args.command == "eval":
        run_eval(runtime, Path(args.cases), top_k=clamp_top_k(args.top_k, runtime.config), json_output=args.json)
        return


def run_eval(runtime: RepoAgentRuntime, cases_path: Path, top_k: int = 6, json_output: bool = False) -> None:
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    records = []
    for case in cases:
        result, _repo_index = runtime.ask(
            repo_path=(cases_path.parent / case["repo"]).resolve(),
            question=case["question"],
            top_k=top_k,
            use_model=False,
            force_rebuild=True,
        )
        top_hit = result.hits[0] if result.hits else None
        rank = _case_match_rank(case, result.hits)
        records.append(
            {
                "question": case["question"],
                "expected_path": case["expected_path"],
                "expected_symbol_contains": case.get("expected_symbol_contains", ""),
                "rank": rank,
                "top_hit": top_hit.chunk.source_label if top_hit else "",
                "top_hits": [hit.chunk.source_label for hit in result.hits[:3]],
                "passed_top1": rank == 1,
                "passed_top3": rank is not None and rank <= 3,
            }
        )

    total = max(len(records), 1)
    metrics = {
        "case_count": len(records),
        "top1_accuracy": sum(1 for record in records if record["passed_top1"]) / total,
        "top3_accuracy": sum(1 for record in records if record["passed_top3"]) / total,
        "mrr": sum((1 / record["rank"]) if record["rank"] else 0 for record in records) / total,
    }

    if json_output:
        print(json.dumps({"metrics": metrics, "cases": records}, ensure_ascii=False, indent=2))
        return

    for record in records:
        ok = record["passed_top3"]
        rank_text = record["rank"] if record["rank"] is not None else "miss"
        print(f"[{'PASS' if ok else 'FAIL'}] {record['question']}")
        print(f"  rank: {rank_text}")
        print(f"  hit: {record['top_hit'] or '<none>'}")
        if record["top_hits"]:
            print(f"  top3: {', '.join(record['top_hits'])}")

    passed_top3 = sum(1 for record in records if record["passed_top3"])
    print(f"\nSummary: {passed_top3}/{len(records)} passed @top3")
    print(f"Top-1 accuracy: {metrics['top1_accuracy']:.2%}")
    print(f"Top-3 accuracy: {metrics['top3_accuracy']:.2%}")
    print(f"MRR: {metrics['mrr']:.3f}")


def _print_engineering_result(result: dict, *, json_output: bool = False) -> None:
    if json_output:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    print(result.get("answer", ""))
    print(f"\n[Run]\n- {result.get('run_id')}")
    print(f"- status={result.get('status')}")
    print(f"- execution_mode={result.get('execution_mode')}")
    print(f"- path={result.get('run_path')}")
    if result.get("workspace_root"):
        print(f"- workspace={result.get('workspace_root')}")
    if result.get("changed_files"):
        print("\n[Changed Files]")
        for relpath in result["changed_files"]:
            print(f"- {relpath}")
    if result.get("verification"):
        print("\n[Verification]")
        for item in result["verification"][-4:]:
            print(f"- {item.get('command')} -> exit {item.get('exit_code')}")
    if result.get("review"):
        print(f"\n[Review]\n{result.get('review')}")


def _case_match_rank(case: dict, hits: list) -> int | None:
    expected_path = str(case["expected_path"]).replace("\\", "/")
    expected_symbol = str(case.get("expected_symbol_contains", "")).lower()
    for rank, hit in enumerate(hits, start=1):
        relpath = hit.chunk.relpath.replace("\\", "/")
        path_ok = expected_path in relpath
        symbol_ok = not expected_symbol or expected_symbol in hit.chunk.symbol_name.lower()
        if path_ok and symbol_ok:
            return rank
    return None


if __name__ == "__main__":
    main()
