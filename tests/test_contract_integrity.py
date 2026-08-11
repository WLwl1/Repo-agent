from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from repo_agent.contract import (
    build_regression_contract,
    contract_fingerprint,
    guard_pr_with_contract,
    render_contract_markdown,
    verify_regression_contract,
    write_contract_output,
)
from repo_agent.runtime import RepoAgentRuntime


def _contract(root: Path, bundle_path: Path) -> dict:
    return {
        "schema_version": "1.0",
        "strategy": "proof_regression_contract",
        "bundle": str(bundle_path),
        "repo_root": str(root),
        "query": "Where is the chat writer?",
        "target": {
            "label": "server.js:writeChatDelta",
            "relpath": "server.js",
            "symbol": "writeChatDelta",
        },
        "proof_context": {
            "status": "proved",
            "top_hit": "server.js:writeChatDelta",
            "route_literals": ["/api/chat"],
            "decoy_count": 2,
            "supporting_path_count": 1,
        },
        "impact_summary": {"risk_level": "high", "exposed_route_count": 1},
        "invariants": [
            {
                "id": "target_exists",
                "level": "P0",
                "description": "The proved target symbol must still exist.",
                "source_label": "server.js:writeChatDelta",
            },
            {
                "id": "route_literals_exist",
                "level": "P0",
                "description": "All route literals used by the proof must still exist.",
                "routes": ["/api/chat"],
            },
        ],
        "verification_commands": [
            "python -m repo_agent replay-proof --bundle <bundle.json> --strict",
            "python -m repo_agent verify-contract --contract <contract.json>",
        ],
    }


def test_contract_fingerprint_ignores_local_paths(tmp_path: Path) -> None:
    left = _contract(tmp_path / "repo-left", tmp_path / "left" / "bundle.json")
    right = deepcopy(left)
    right["bundle"] = str(tmp_path / "right" / "bundle.json")
    right["repo_root"] = str(tmp_path / "repo-right")

    assert contract_fingerprint(left)["value"] == contract_fingerprint(right)["value"]


def test_contract_fingerprint_changes_when_invariant_changes(tmp_path: Path) -> None:
    original = _contract(tmp_path / "repo", tmp_path / "bundle.json")
    mutated = deepcopy(original)
    route_invariant = next(item for item in mutated["invariants"] if item["id"] == "route_literals_exist")
    route_invariant["routes"] = ["/api/chat/v2"]

    assert contract_fingerprint(original)["value"] != contract_fingerprint(mutated)["value"]


def test_built_contract_verification_and_guard_share_fingerprint(tmp_path: Path) -> None:
    runtime = RepoAgentRuntime(Path.cwd())
    _bundle, bundle_path = runtime.generate_bundle(
        repo_path=Path.cwd() / "examples" / "counterfactual_agent_app",
        question="Which function finally writes streamed tokens for the public /api/chat endpoint?",
        target="generic",
        fmt="json",
        force_rebuild=True,
        output_path=tmp_path / "counterfactual-evidence.json",
    )
    contract = build_regression_contract(bundle_path)
    contract_path = write_contract_output(contract, tmp_path / "contract.json")
    verification = verify_regression_contract(contract_path)
    guard = guard_pr_with_contract(contract_path, changed_files=["server.js"])
    markdown = render_contract_markdown(contract)
    stored = json.loads(contract_path.read_text(encoding="utf-8"))

    expected = contract_fingerprint(contract)["value"]
    assert stored["contract_fingerprint"]["value"] == expected
    assert verification["contract_fingerprint"]["value"] == expected
    assert guard["contract_fingerprint"]["value"] == expected
    assert "Contract fingerprint:" in markdown
