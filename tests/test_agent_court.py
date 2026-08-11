from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from repo_agent.court import build_agent_court, render_agent_court_markdown, write_agent_court_output
from repo_agent.proof import build_proof_scorecard
from repo_agent.runtime import RepoAgentRuntime


def test_agent_court_accepts_proved_bundle_with_red_team_and_temporal_evidence(tmp_path: Path) -> None:
    bundle_path = _demo_bundle(tmp_path)
    proof_scorecard = build_proof_scorecard(bundle_path)
    attack_scorecard = _passing_attack_scorecard()
    temporal_scorecard = _passing_temporal_scorecard()

    payload = build_agent_court(
        bundle_path,
        proof_scorecard=proof_scorecard,
        attack_scorecard=attack_scorecard,
        temporal_scorecard=temporal_scorecard,
    )
    markdown = render_agent_court_markdown(payload)
    output_path = write_agent_court_output(payload, tmp_path / "agent-court.md")

    assert payload["strategy"] == "multi_agent_evidence_court"
    assert payload["verdict"]["status"] == "accepted"
    assert payload["verdict"]["score"] == 100
    assert payload["verdict"]["grade"] == "A"
    assert payload["metrics"]["agent_count"] == 6
    assert payload["metrics"]["claim_count"] == 6
    assert payload["metrics"]["passed_claim_count"] == 6
    assert payload["metrics"]["challenge_count"] >= 3
    assert all(len(claim["evidence_hash"]) == 12 for claim in payload["claims"])
    assert any(challenge["id"].startswith("weak_signal_generated_decoy") for challenge in payload["challenges"])
    assert "## Claim Ledger" in markdown
    assert "## Challenge Ledger" in markdown
    assert output_path.is_file()


def test_agent_court_contests_unmitigated_red_team_decoys_and_cli_writes_json(tmp_path: Path) -> None:
    bundle_path = _demo_bundle(tmp_path)
    attack_scorecard_path = tmp_path / "attack-scorecard.json"
    temporal_scorecard_path = tmp_path / "temporal-scorecard.json"
    attack_scorecard_path.write_text(json.dumps(_failing_attack_scorecard()), encoding="utf-8")
    temporal_scorecard_path.write_text(json.dumps(_passing_temporal_scorecard()), encoding="utf-8")

    payload = build_agent_court(
        bundle_path,
        attack_scorecard=json.loads(attack_scorecard_path.read_text(encoding="utf-8")),
        temporal_scorecard=json.loads(temporal_scorecard_path.read_text(encoding="utf-8")),
    )
    output_path = tmp_path / "agent-court.json"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "repo_agent",
            "agent-court",
            "--bundle",
            str(bundle_path),
            "--attack-scorecard",
            str(attack_scorecard_path),
            "--temporal-scorecard",
            str(temporal_scorecard_path),
            "--output",
            str(output_path),
            "--json",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert payload["verdict"]["status"] == "needs_review"
    assert "generated_attack_claim" in payload["verdict"]["blocking_failures"]
    assert any(challenge["severity"] == "error" and not challenge["discharged"] for challenge in payload["challenges"])
    assert result.returncode == 0
    assert output_path.is_file()
    assert json.loads(output_path.read_text(encoding="utf-8"))["verdict"]["status"] == "needs_review"


def _demo_bundle(tmp_path: Path) -> Path:
    runtime = RepoAgentRuntime(Path.cwd())
    _bundle, bundle_path = runtime.generate_bundle(
        repo_path=Path("examples/counterfactual_agent_app"),
        question="Which function finally writes streamed tokens for the public /api/chat endpoint?",
        target="generic",
        fmt="json",
        top_k=6,
        use_model=False,
        force_rebuild=True,
        output_path=tmp_path / "proof.bundle.json",
    )
    return bundle_path


def _passing_attack_scorecard() -> dict:
    return {
        "status": "pass",
        "score": 100,
        "items": [
            {"id": "attack_resistance", "passed": True},
            {"id": "generated_decoy_mitigation", "passed": True},
            {"id": "mitigation_signal_coverage", "passed": True},
            {"id": "proof_proved_rate", "passed": True},
        ],
        "unmitigated_decoys": [],
        "weak_signal_decoys": [
            {"case": "documentation_bait_writer", "decoy": "server.js:writeChatDeltaDocumentation", "rank": 8}
        ],
    }


def _failing_attack_scorecard() -> dict:
    return {
        "status": "fail",
        "score": 0,
        "items": [
            {"id": "attack_resistance", "passed": False},
            {"id": "generated_decoy_mitigation", "passed": False},
        ],
        "unmitigated_decoys": [
            {"case": "admin_shadow_writer", "decoy": "server.js:writeChatDeltaForAdminShadow", "rank": 1}
        ],
        "weak_signal_decoys": [],
    }


def _passing_temporal_scorecard() -> dict:
    return {
        "status": "pass",
        "score": 100,
        "items": [
            {"id": "successor_top1", "passed": True},
            {"id": "negative_control_abstention", "passed": True},
            {"id": "causal_graph_delta", "passed": True},
            {"id": "migration_ready", "passed": True},
        ],
    }
