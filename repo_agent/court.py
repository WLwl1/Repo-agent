from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .proof import build_proof_scorecard, load_evidence_bundle


def build_agent_court(
    bundle_path: Path,
    *,
    repo_path: Path | None = None,
    proof_scorecard: dict[str, Any] | None = None,
    proof_scorecard_path: Path | None = None,
    attack_scorecard: dict[str, Any] | None = None,
    attack_scorecard_path: Path | None = None,
    temporal_scorecard: dict[str, Any] | None = None,
    temporal_scorecard_path: Path | None = None,
    strict: bool = True,
) -> dict[str, Any]:
    bundle = load_evidence_bundle(bundle_path)
    proof = dict(bundle.get("proof") or {})
    proof_scorecard = proof_scorecard or _load_optional_json(proof_scorecard_path) or build_proof_scorecard(
        bundle_path,
        repo_path=repo_path,
        strict=strict,
    )
    attack_scorecard = attack_scorecard or _load_optional_json(attack_scorecard_path)
    temporal_scorecard = temporal_scorecard or _load_optional_json(temporal_scorecard_path)

    claims = [
        _claim(
            "retrieval_advocate",
            "top_hit_claim",
            "The selected top hit is explicitly proved by the evidence bundle.",
            proof.get("status") == "proved" and bool(proof.get("top_hit")),
            15,
            {"proof_status": proof.get("status", "unknown"), "top_hit": proof.get("top_hit", "")},
        ),
        _claim(
            "graph_navigator",
            "route_path_claim",
            "A route-to-target execution path supports the answer.",
            bool(proof.get("route_literals")) and bool(proof.get("supporting_paths")),
            15,
            {
                "routes": list(proof.get("route_literals") or []),
                "supporting_paths": list(proof.get("supporting_paths") or []),
            },
        ),
    ]
    claims.extend(_proof_scorecard_claims(proof_scorecard))
    claims.extend(_attack_scorecard_claims(attack_scorecard))
    claims.extend(_temporal_scorecard_claims(temporal_scorecard))

    challenges = _build_challenges(proof, proof_scorecard, attack_scorecard, temporal_scorecard)
    active_claims = [claim for claim in claims if claim.get("active", True)]
    active_weight = sum(int(claim.get("weight", 0)) for claim in active_claims)
    passed_weight = sum(int(claim.get("weight", 0)) for claim in active_claims if claim.get("passed"))
    score = round((passed_weight / active_weight) * 100) if active_weight else 0
    blocking_failures = [
        claim
        for claim in active_claims
        if claim.get("required", True) and not claim.get("passed")
    ]
    open_challenges = [item for item in challenges if item.get("severity") == "error" and not item.get("discharged")]
    verdict_status = _court_status(score, blocking_failures, open_challenges)
    agents = _agents_from_claims(claims)

    return {
        "schema_version": "1.0",
        "strategy": "multi_agent_evidence_court",
        "bundle": str(bundle_path),
        "repo_root": str(repo_path or (bundle.get("repository") or {}).get("root", "")),
        "query": bundle.get("query", ""),
        "target": proof.get("top_hit", ""),
        "strict": strict,
        "verdict": {
            "status": verdict_status,
            "accepted": verdict_status == "accepted",
            "score": score,
            "grade": _grade(score),
            "passed_weight": passed_weight,
            "active_weight": active_weight,
            "blocking_failures": [claim["id"] for claim in blocking_failures],
            "open_challenges": [item["id"] for item in open_challenges],
        },
        "metrics": {
            "agent_count": len(agents),
            "claim_count": len(active_claims),
            "passed_claim_count": sum(1 for claim in active_claims if claim.get("passed")),
            "challenge_count": len(challenges),
            "discharged_challenge_count": sum(1 for item in challenges if item.get("discharged")),
            "optional_claim_count": sum(1 for claim in claims if not claim.get("active", True)),
        },
        "agents": agents,
        "claims": claims,
        "challenges": challenges,
        "transcript": _build_transcript(claims, challenges, verdict_status),
    }


def render_agent_court_markdown(payload: dict[str, Any]) -> str:
    verdict = dict(payload.get("verdict") or {})
    metrics = dict(payload.get("metrics") or {})
    lines = [
        "# Repo Agent Multi-Agent Evidence Court",
        "",
        f"- Verdict: `{verdict.get('status', 'unknown')}`",
        f"- Grade: `{verdict.get('grade', '')}`",
        f"- Score: `{int(verdict.get('score', 0))}/100`",
        f"- Query: {payload.get('query', '')}",
        f"- Target: `{payload.get('target', '')}`",
        f"- Agents: `{int(metrics.get('agent_count', 0))}`",
        f"- Claims: `{int(metrics.get('passed_claim_count', 0))}/{int(metrics.get('claim_count', 0))}` passed",
        f"- Challenges: `{int(metrics.get('discharged_challenge_count', 0))}/{int(metrics.get('challenge_count', 0))}` discharged",
        "",
        "## Claim Ledger",
        "",
        "| Agent | Claim | Result | Weight | Evidence |",
        "| --- | --- | --- | ---: | --- |",
    ]
    for claim in payload.get("claims", []):
        if not claim.get("active", True):
            result = "N/A"
        else:
            result = "PASS" if claim.get("passed") else "FAIL"
        lines.append(
            f"| `{claim.get('agent', '')}` | `{claim.get('id', '')}` | {result} | "
            f"{int(claim.get('weight', 0))} | `{claim.get('evidence_hash', '')}` |"
        )

    lines.extend(
        [
            "",
            "## Challenge Ledger",
            "",
            "| Challenge | Severity | Discharged | Evidence |",
            "| --- | --- | --- | --- |",
        ]
    )
    for challenge in payload.get("challenges", []):
        discharged = "yes" if challenge.get("discharged") else "no"
        lines.append(
            f"| `{challenge.get('id', '')}` | `{challenge.get('severity', '')}` | "
            f"{discharged} | `{challenge.get('evidence_hash', '')}` |"
        )

    lines.extend(
        [
            "",
            "## Arbiter Transcript",
            "",
        ]
    )
    for item in payload.get("transcript", []):
        lines.append(f"- `{item.get('agent', '')}`: {item.get('message', '')}")
    lines.append("")
    return "\n".join(lines)


def write_agent_court_output(payload: dict[str, Any], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.suffix.lower() == ".json":
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        output_path.write_text(render_agent_court_markdown(payload), encoding="utf-8")
    return output_path


def _proof_scorecard_claims(scorecard: dict[str, Any]) -> list[dict[str, Any]]:
    metrics = dict(scorecard.get("metrics") or {})
    score_items = {str(item.get("name", "")): bool(item.get("passed")) for item in scorecard.get("score_items", [])}
    return [
        _claim(
            "proof_verifier",
            "strict_replay_claim",
            "Strict proof replay is valid and graph edges are verified.",
            metrics.get("strict_replay_status") == "valid" and score_items.get("proof_edges_verified", False),
            20,
            {
                "strict_replay_status": metrics.get("strict_replay_status", "unknown"),
                "proof_edges_verified": score_items.get("proof_edges_verified", False),
            },
        ),
        _claim(
            "mutation_skeptic",
            "mutation_resistance_claim",
            "Mutation testing detects every proof-breaking perturbation.",
            float(metrics.get("mutation_detection_rate", 0.0)) >= 1.0,
            15,
            {
                "mutation_count": metrics.get("mutation_count", 0),
                "mutation_detected": metrics.get("mutation_detected", 0),
                "mutation_detection_rate": metrics.get("mutation_detection_rate", 0.0),
            },
        ),
    ]


def _attack_scorecard_claims(scorecard: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not scorecard:
        return [
            _claim(
                "red_team_skeptic",
                "generated_attack_claim",
                "Generated adversarial attacks were not supplied to this court.",
                False,
                0,
                {"status": "not_supplied"},
                active=False,
                required=False,
            )
        ]
    items = {str(item.get("id", "")): bool(item.get("passed")) for item in scorecard.get("items", [])}
    return [
        _claim(
            "red_team_skeptic",
            "generated_attack_claim",
            "Generated adversarial attacks are resisted above threshold.",
            scorecard.get("status") == "pass" and items.get("attack_resistance", False),
            20,
            {
                "status": scorecard.get("status", "unknown"),
                "score": scorecard.get("score", 0),
                "attack_resistance": items.get("attack_resistance", False),
                "unmitigated_decoys": len(list(scorecard.get("unmitigated_decoys") or [])),
            },
        )
    ]


def _temporal_scorecard_claims(scorecard: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not scorecard:
        return [
            _claim(
                "temporal_guardian",
                "temporal_repair_claim",
                "Temporal repair benchmark was not supplied to this court.",
                False,
                0,
                {"status": "not_supplied"},
                active=False,
                required=False,
            )
        ]
    items = {str(item.get("id", "")): bool(item.get("passed")) for item in scorecard.get("items", [])}
    return [
        _claim(
            "temporal_guardian",
            "temporal_repair_claim",
            "Temporal repair finds successor targets and abstains on negative controls.",
            scorecard.get("status") == "pass"
            and items.get("successor_top1", False)
            and items.get("negative_control_abstention", False),
            15,
            {
                "status": scorecard.get("status", "unknown"),
                "score": scorecard.get("score", 0),
                "successor_top1": items.get("successor_top1", False),
                "negative_control_abstention": items.get("negative_control_abstention", False),
            },
        )
    ]


def _build_challenges(
    proof: dict[str, Any],
    proof_scorecard: dict[str, Any],
    attack_scorecard: dict[str, Any] | None,
    temporal_scorecard: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    challenges: list[dict[str, Any]] = []
    for index, item in enumerate(proof.get("decoy_audit") or [], start=1):
        challenges.append(
            _challenge(
                f"proof_decoy_{index}",
                "warning",
                bool(item.get("rejected")),
                {
                    "candidate": item.get("candidate", ""),
                    "rejected": item.get("rejected", False),
                    "conflicting_roles": item.get("conflicting_roles", []),
                    "requested_routes": item.get("requested_routes", []),
                },
            )
        )
    for item in proof_scorecard.get("replay", {}).get("checks", []):
        if not item.get("passed"):
            challenges.append(
                _challenge(
                    f"replay_check_{item.get('name', 'unknown')}",
                    "error",
                    False,
                    {"check": item.get("name", ""), "detail": item.get("detail", "")},
                )
            )
    if attack_scorecard:
        for index, item in enumerate(attack_scorecard.get("unmitigated_decoys") or [], start=1):
            challenges.append(
                _challenge(
                    f"unmitigated_generated_decoy_{index}",
                    "error",
                    False,
                    item,
                )
            )
        for index, item in enumerate(attack_scorecard.get("weak_signal_decoys") or [], start=1):
            challenges.append(
                _challenge(
                    f"weak_signal_generated_decoy_{index}",
                    "warning",
                    True,
                    item,
                )
            )
    if temporal_scorecard:
        for item in temporal_scorecard.get("items", []):
            if not item.get("passed"):
                challenges.append(
                    _challenge(
                        f"temporal_threshold_{item.get('id', 'unknown')}",
                        "error",
                        False,
                        item,
                    )
                )
    return challenges


def _claim(
    agent: str,
    claim_id: str,
    statement: str,
    passed: bool,
    weight: int,
    evidence: dict[str, Any],
    *,
    active: bool = True,
    required: bool = True,
) -> dict[str, Any]:
    return {
        "agent": agent,
        "id": claim_id,
        "statement": statement,
        "passed": bool(passed),
        "weight": int(weight),
        "active": active,
        "required": required,
        "evidence": evidence,
        "evidence_hash": _evidence_hash(evidence),
    }


def _challenge(challenge_id: str, severity: str, discharged: bool, evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": challenge_id,
        "severity": severity,
        "discharged": bool(discharged),
        "evidence": evidence,
        "evidence_hash": _evidence_hash(evidence),
    }


def _agents_from_claims(claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    agents = []
    for name in dict.fromkeys(str(claim.get("agent", "")) for claim in claims):
        agent_claims = [claim for claim in claims if claim.get("agent") == name]
        active = [claim for claim in agent_claims if claim.get("active", True)]
        agents.append(
            {
                "name": name,
                "claim_count": len(active),
                "passed_claim_count": sum(1 for claim in active if claim.get("passed")),
                "role": _agent_role(name),
            }
        )
    return agents


def _build_transcript(claims: list[dict[str, Any]], challenges: list[dict[str, Any]], verdict_status: str) -> list[dict[str, str]]:
    failed_claims = [claim["id"] for claim in claims if claim.get("active", True) and not claim.get("passed")]
    open_challenges = [item["id"] for item in challenges if item.get("severity") == "error" and not item.get("discharged")]
    transcript = [
        {
            "agent": "arbiter",
            "message": f"verdict={verdict_status}; failed_claims={', '.join(failed_claims) or 'none'}; open_challenges={', '.join(open_challenges) or 'none'}",
        }
    ]
    for claim in claims:
        if claim.get("active", True):
            result = "supports" if claim.get("passed") else "contests"
            transcript.append({"agent": str(claim.get("agent", "")), "message": f"{result} {claim.get('id', '')}"})
    return transcript


def _court_status(score: int, blocking_failures: list[dict[str, Any]], open_challenges: list[dict[str, Any]]) -> str:
    if not blocking_failures and not open_challenges and score >= 90:
        return "accepted"
    if score >= 70:
        return "needs_review"
    return "rejected"


def _grade(score: int) -> str:
    if score >= 95:
        return "A"
    if score >= 85:
        return "B"
    if score >= 70:
        return "C"
    return "F"


def _evidence_hash(evidence: dict[str, Any]) -> str:
    encoded = json.dumps(evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:12]


def _load_optional_json(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _agent_role(name: str) -> str:
    return {
        "retrieval_advocate": "Proposes the answer from proof-carrying retrieval.",
        "graph_navigator": "Checks route and graph-path support.",
        "proof_verifier": "Replays proof invariants against the repository.",
        "mutation_skeptic": "Attacks the proof checker with synthetic corruptions.",
        "red_team_skeptic": "Uses generated adversarial repositories to contest the answer.",
        "temporal_guardian": "Checks whether proof repair handles code evolution.",
    }.get(name, "Participates in the evidence court.")
