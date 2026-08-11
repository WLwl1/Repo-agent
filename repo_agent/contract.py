from __future__ import annotations

import json
import hashlib
from pathlib import Path
from typing import Any

from .impact import analyze_impact_bundle
from .indexer import RepositoryIndex, build_index
from .proof import load_evidence_bundle, replay_proof_bundle


def contract_fingerprint(contract: dict[str, Any]) -> dict[str, Any]:
    canonical = _canonical_contract_payload(contract)
    encoded = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "algorithm": "sha256",
        "scope": "stable_regression_contract",
        "value": hashlib.sha256(encoded).hexdigest(),
        "canonical_fields": sorted(canonical.keys()),
    }


def build_regression_contract(
    bundle_path: Path,
    repo_path: Path | None = None,
    *,
    max_depth: int = 3,
) -> dict[str, Any]:
    bundle = load_evidence_bundle(bundle_path)
    proof = dict(bundle.get("proof") or {})
    repository = dict(bundle.get("repository") or {})
    selected_repo = repo_path or Path(str(repository.get("root", "")))
    if not str(selected_repo):
        raise ValueError("repository path is required when the bundle does not contain repository.root")
    impact = analyze_impact_bundle(bundle_path, repo_path=selected_repo, max_depth=max_depth)
    summary = dict(impact.get("impact_summary") or {})
    target = dict(impact.get("target") or {})
    route_literals = [str(item) for item in proof.get("route_literals", []) if str(item)]
    decoys = [str(item.get("candidate", "")) for item in proof.get("decoy_audit", []) if item.get("candidate")]
    supporting_paths = [
        {
            "route": item.get("route", ""),
            "path": list(item.get("path") or []),
        }
        for item in proof.get("supporting_paths", [])
    ]

    invariants = [
        {
            "id": "target_exists",
            "level": "P0",
            "description": "The proved target symbol must still exist.",
            "source_label": proof.get("top_hit") or target.get("label", ""),
        },
        {
            "id": "strict_proof_replay",
            "level": "P0",
            "description": "Strict proof replay must remain valid.",
        },
        {
            "id": "route_literals_exist",
            "level": "P0",
            "description": "All route literals used by the proof must still exist.",
            "routes": route_literals,
        },
        {
            "id": "supporting_paths_exist",
            "level": "P0",
            "description": "The proof route-to-target execution paths must still resolve.",
            "paths": supporting_paths,
        },
        {
            "id": "decoys_remain_rejected",
            "level": "P1",
            "description": "Previously audited decoy candidates must still be rejected.",
            "candidates": decoys,
        },
        {
            "id": "impact_route_exposure_preserved",
            "level": "P1",
            "description": "The impact analysis must still detect at least the original route exposure.",
            "minimum_exposed_routes": int(summary.get("exposed_route_count", 0)),
            "routes": sorted({str(item.get("route", "")) for item in impact.get("exposed_routes", []) if item.get("route")}),
        },
    ]

    contract = {
        "schema_version": "1.0",
        "strategy": "proof_regression_contract",
        "bundle": str(bundle_path),
        "repo_root": str(selected_repo),
        "query": bundle.get("query", ""),
        "target": target,
        "proof_context": {
            "status": proof.get("status", "unknown"),
            "top_hit": proof.get("top_hit", ""),
            "route_literals": route_literals,
            "decoy_count": len(decoys),
            "supporting_path_count": len(supporting_paths),
        },
        "impact_summary": summary,
        "invariants": invariants,
        "verification_commands": [
            "python -m repo_agent replay-proof --bundle <bundle.json> --strict",
            "python -m repo_agent impact --bundle <bundle.json>",
            "python -m repo_agent verify-contract --contract <contract.json>",
        ],
    }
    contract["contract_fingerprint"] = contract_fingerprint(contract)
    return contract


def verify_regression_contract(contract_path: Path, repo_path: Path | None = None) -> dict[str, Any]:
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    selected_repo = repo_path or Path(str(contract.get("repo_root", "")))
    if not str(selected_repo):
        raise ValueError("repository path is required when the contract does not contain repo_root")
    repo_index = build_index(selected_repo)
    bundle_path = _resolve_contract_bundle_path(contract_path, str(contract.get("bundle", "")))
    replay = replay_proof_bundle(bundle_path, repo_path=selected_repo, strict=True)
    impact = analyze_impact_bundle(bundle_path, repo_path=selected_repo)
    checks = [
        _check_contract_invariant(item, repo_index, replay, impact)
        for item in contract.get("invariants", [])
    ]
    passed = all(item.get("passed") for item in checks)
    return {
        "schema_version": "1.0",
        "strategy": "proof_regression_contract_verification",
        "status": "valid" if passed else "invalid",
        "valid": passed,
        "contract": str(contract_path),
        "bundle": str(bundle_path),
        "repo_root": str(selected_repo),
        "contract_fingerprint": contract_fingerprint(contract),
        "query": contract.get("query", ""),
        "checks": checks,
        "summary": {
            "check_count": len(checks),
            "passed_count": sum(1 for item in checks if item.get("passed")),
            "failed_count": sum(1 for item in checks if not item.get("passed")),
        },
    }


def guard_pr_with_contract(
    contract_path: Path,
    changed_files: list[str],
    repo_path: Path | None = None,
    fail_on: str = "fail",
) -> dict[str, Any]:
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    verification = verify_regression_contract(contract_path, repo_path=repo_path)
    normalized_changed = sorted({_normalize_relpath(path) for path in changed_files if str(path).strip()})
    protected = _protected_surfaces(contract)
    touched = [
        {
            "relpath": relpath,
            "reason": reason,
            "surface": surface,
        }
        for relpath in normalized_changed
        for surface, reason in _matching_surfaces(relpath, protected)
    ]
    touched_files = sorted({item["relpath"] for item in touched})
    requires_verification = bool(touched_files)
    verification_failed = not bool(verification.get("valid"))
    if verification_failed:
        status = "fail"
    elif requires_verification:
        status = "warn"
    else:
        status = "pass"
    required_commands = list(contract.get("verification_commands") or [])
    if requires_verification and "python -m repo_agent verify-contract --contract <contract.json>" not in required_commands:
        required_commands.append("python -m repo_agent verify-contract --contract <contract.json>")
    annotations = _github_annotations(status, touched, verification)
    exit_code = _guard_exit_code(status, fail_on)
    return {
        "schema_version": "1.0",
        "strategy": "proof_backed_pr_guard",
        "status": status,
        "contract": str(contract_path),
        "contract_fingerprint": contract_fingerprint(contract),
        "repo_root": str(repo_path or contract.get("repo_root", "")),
        "changed_files": normalized_changed,
        "requires_verification": requires_verification,
        "touched_protected_files": touched_files,
        "touched_surfaces": touched,
        "protected_surfaces": protected,
        "required_commands": required_commands if requires_verification or verification_failed else [],
        "fail_on": fail_on,
        "exit_code": exit_code,
        "github_annotations": annotations,
        "contract_verification": verification,
        "summary": {
            "changed_file_count": len(normalized_changed),
            "touched_protected_file_count": len(touched_files),
            "contract_status": verification.get("status", "unknown"),
        },
    }


def render_contract_markdown(payload: dict[str, Any]) -> str:
    proof = dict(payload.get("proof_context") or {})
    impact = dict(payload.get("impact_summary") or {})
    lines = [
        "# Repo Agent Proof Regression Contract",
        "",
        f"- Strategy: `{payload.get('strategy', '')}`",
        f"- Repository: `{payload.get('repo_root', '')}`",
        f"- Query: {payload.get('query', '')}",
        f"- Contract fingerprint: `{(payload.get('contract_fingerprint') or {}).get('value', '')}`",
        f"- Target: `{proof.get('top_hit', '')}`",
        f"- Proof status: `{proof.get('status', '')}`",
        f"- Risk level: `{impact.get('risk_level', 'unknown')}`",
        f"- Exposed routes: `{impact.get('exposed_route_count', 0)}`",
        "",
        "## Invariants",
        "",
        "| Level | Invariant | Description |",
        "| --- | --- | --- |",
    ]
    for item in payload.get("invariants", []):
        lines.append(f"| `{item.get('level', '')}` | `{item.get('id', '')}` | {item.get('description', '')} |")
    lines.extend(["", "## Verification Commands", ""])
    for command in payload.get("verification_commands", []):
        lines.append(f"- `{command}`")
    lines.append("")
    return "\n".join(lines)


def render_pr_guard_markdown(payload: dict[str, Any]) -> str:
    status = str(payload.get("status", "unknown")).upper()
    summary = dict(payload.get("summary") or {})
    lines = [
        "# Repo Agent Proof-Backed PR Guard",
        "",
        f"- Status: `{status}`",
        f"- Contract: `{payload.get('contract', '')}`",
        f"- Contract fingerprint: `{(payload.get('contract_fingerprint') or {}).get('value', '')}`",
        f"- Changed files: `{summary.get('changed_file_count', 0)}`",
        f"- Protected files touched: `{summary.get('touched_protected_file_count', 0)}`",
        f"- Contract verification: `{summary.get('contract_status', 'unknown')}`",
        f"- Fail-on policy: `{payload.get('fail_on', 'fail')}`",
        f"- Suggested exit code: `{int(payload.get('exit_code', 0))}`",
        "",
        "## Touched Protected Surfaces",
        "",
    ]
    touched = list(payload.get("touched_surfaces") or [])
    if touched:
        lines.extend(["| File | Surface | Reason |", "| --- | --- | --- |"])
        for item in touched:
            lines.append(f"| `{item.get('relpath', '')}` | `{item.get('surface', '')}` | {item.get('reason', '')} |")
    else:
        lines.append("No changed file touched a protected proof surface.")
    commands = list(payload.get("required_commands") or [])
    if commands:
        lines.extend(["", "## Required Commands", ""])
        for command in commands:
            lines.append(f"- `{command}`")
    failed_checks = [
        item
        for item in (payload.get("contract_verification") or {}).get("checks", [])
        if not item.get("passed")
    ]
    if failed_checks:
        lines.extend(["", "## Failed Contract Checks", "", "| Invariant | Detail |", "| --- | --- |"])
        for item in failed_checks:
            lines.append(f"| `{item.get('id', '')}` | {item.get('detail', '')} |")
    annotations = list(payload.get("github_annotations") or [])
    if annotations:
        lines.extend(["", "## GitHub Annotations", ""])
        for annotation in annotations:
            lines.append(f"- `{annotation}`")
    lines.append("")
    return "\n".join(lines)


def render_pr_guard_sarif(payload: dict[str, Any]) -> dict[str, Any]:
    results = []
    for item in payload.get("touched_surfaces", []):
        relpath = str(item.get("relpath", ""))
        surface = str(item.get("surface", "protected proof surface"))
        reason = str(item.get("reason", "changed file touches a protected proof surface"))
        results.append(
            {
                "ruleId": "repo-agent/protected-proof-surface",
                "level": "warning",
                "message": {"text": f"{surface}: {reason}"},
                "locations": [_sarif_location(relpath)],
                "properties": {
                    "contract": payload.get("contract", ""),
                    "guardStatus": payload.get("status", ""),
                    "requiredCommands": payload.get("required_commands", []),
                },
            }
        )
    for check in (payload.get("contract_verification") or {}).get("checks", []):
        if check.get("passed"):
            continue
        results.append(
            {
                "ruleId": "repo-agent/contract-invariant-failed",
                "level": "error",
                "message": {"text": f"{check.get('id', '')}: {check.get('detail', '')}"},
                "locations": [_sarif_location("")],
                "properties": {
                    "contract": payload.get("contract", ""),
                    "invariant": check.get("id", ""),
                    "description": check.get("description", ""),
                },
            }
        )
    return {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "Repo Agent Proof-Backed PR Guard",
                        "informationUri": "https://github.com/",
                        "rules": [
                            {
                                "id": "repo-agent/protected-proof-surface",
                                "name": "Protected proof surface touched",
                                "shortDescription": {"text": "A changed file touches a proof-protected surface."},
                                "fullDescription": {
                                    "text": "Repo Agent found that a changed file intersects a proof regression contract surface and requires evidence replay before merge."
                                },
                                "defaultConfiguration": {"level": "warning"},
                            },
                            {
                                "id": "repo-agent/contract-invariant-failed",
                                "name": "Proof regression contract invariant failed",
                                "shortDescription": {"text": "A proof regression contract invariant failed."},
                                "fullDescription": {
                                    "text": "Repo Agent replayed the proof regression contract and found an invariant that no longer holds."
                                },
                                "defaultConfiguration": {"level": "error"},
                            },
                        ],
                    }
                },
                "results": results,
                "properties": {
                    "status": payload.get("status", ""),
                    "failOn": payload.get("fail_on", ""),
                    "requiresVerification": payload.get("requires_verification", False),
                },
            }
        ],
    }


def render_contract_verification_markdown(payload: dict[str, Any]) -> str:
    status = "PASS" if payload.get("valid") else "FAIL"
    summary = dict(payload.get("summary") or {})
    lines = [
        "# Repo Agent Proof Regression Contract Verification",
        "",
        f"- Status: `{status}`",
        f"- Contract: `{payload.get('contract', '')}`",
        f"- Contract fingerprint: `{(payload.get('contract_fingerprint') or {}).get('value', '')}`",
        f"- Repository: `{payload.get('repo_root', '')}`",
        f"- Checks: `{summary.get('passed_count', 0)}/{summary.get('check_count', 0)}`",
        "",
        "| Result | Invariant | Detail |",
        "| --- | --- | --- |",
    ]
    for item in payload.get("checks", []):
        result = "PASS" if item.get("passed") else "FAIL"
        lines.append(f"| {result} | `{item.get('id', '')}` | {item.get('detail', '')} |")
    lines.append("")
    return "\n".join(lines)


def write_contract_output(payload: dict[str, Any], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.suffix.lower() == ".json":
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        output_path.write_text(render_contract_markdown(payload), encoding="utf-8")
    return output_path


def write_contract_verification_output(payload: dict[str, Any], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.suffix.lower() == ".json":
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        output_path.write_text(render_contract_verification_markdown(payload), encoding="utf-8")
    return output_path


def write_pr_guard_output(payload: dict[str, Any], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.suffix.lower() == ".json":
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        output_path.write_text(render_pr_guard_markdown(payload), encoding="utf-8")
    return output_path


def write_pr_guard_sarif(payload: dict[str, Any], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(render_pr_guard_sarif(payload), ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def _canonical_contract_payload(contract: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": contract.get("schema_version", ""),
        "strategy": contract.get("strategy", ""),
        "query": contract.get("query", ""),
        "target": contract.get("target", {}),
        "proof_context": contract.get("proof_context", {}),
        "impact_summary": contract.get("impact_summary", {}),
        "invariants": contract.get("invariants", []),
        "verification_commands": contract.get("verification_commands", []),
    }


def _check_contract_invariant(
    invariant: dict[str, Any],
    repo_index: RepositoryIndex,
    replay: dict[str, Any],
    impact: dict[str, Any],
) -> dict[str, Any]:
    invariant_id = str(invariant.get("id", ""))
    labels = {chunk.source_label for chunk in repo_index.chunks}
    routes = {chunk.route_path for chunk in repo_index.chunks if chunk.route_path}
    if invariant_id == "target_exists":
        label = str(invariant.get("source_label", ""))
        return _check_result(invariant, bool(label and label in labels), label or "missing target label")
    if invariant_id == "strict_proof_replay":
        return _check_result(invariant, replay.get("status") == "valid", f"replay status {replay.get('status')}")
    if invariant_id == "route_literals_exist":
        missing = [route for route in invariant.get("routes", []) if route not in routes]
        return _check_result(invariant, not missing, "all routes present" if not missing else f"missing: {', '.join(missing)}")
    if invariant_id == "supporting_paths_exist":
        missing = []
        for path_item in invariant.get("paths", []):
            for label in path_item.get("path", []):
                if label not in labels:
                    missing.append(str(label))
        unique_missing = sorted(set(missing))
        return _check_result(invariant, not unique_missing, "all path nodes present" if not unique_missing else f"missing: {', '.join(unique_missing)}")
    if invariant_id == "decoys_remain_rejected":
        replay_checks = {item.get("name"): item for item in replay.get("checks", [])}
        decoy_check = replay_checks.get("decoy_audit_still_rejected", {})
        return _check_result(invariant, bool(decoy_check.get("passed", True)), str(decoy_check.get("detail", "decoy audit not recorded")))
    if invariant_id == "impact_route_exposure_preserved":
        expected_routes = {str(route) for route in invariant.get("routes", []) if str(route)}
        current_routes = {str(item.get("route", "")) for item in impact.get("exposed_routes", []) if item.get("route")}
        missing = sorted(expected_routes - current_routes)
        minimum = int(invariant.get("minimum_exposed_routes", 0))
        current_count = int((impact.get("impact_summary") or {}).get("exposed_route_count", 0))
        passed = not missing and current_count >= minimum
        detail = f"current exposed routes {current_count}, expected at least {minimum}"
        if missing:
            detail += f"; missing: {', '.join(missing)}"
        return _check_result(invariant, passed, detail)
    return _check_result(invariant, False, "unknown invariant")


def _check_result(invariant: dict[str, Any], passed: bool, detail: str) -> dict[str, Any]:
    return {
        "id": invariant.get("id", ""),
        "level": invariant.get("level", ""),
        "description": invariant.get("description", ""),
        "passed": passed,
        "detail": detail,
    }


def _resolve_contract_bundle_path(contract_path: Path, raw_path: str) -> Path:
    bundle_path = Path(raw_path)
    if bundle_path.is_absolute() or bundle_path.exists():
        return bundle_path
    sibling = contract_path.parent / bundle_path.name
    if sibling.exists():
        return sibling
    return bundle_path


def _guard_exit_code(status: str, fail_on: str) -> int:
    normalized = fail_on.lower()
    if normalized == "never":
        return 0
    if normalized == "warn":
        return 1 if status in {"warn", "fail"} else 0
    return 1 if status == "fail" else 0


def _github_annotations(status: str, touched: list[dict[str, str]], verification: dict[str, Any]) -> list[str]:
    annotations = []
    annotation_level = "error" if status == "fail" else "warning"
    for item in touched:
        relpath = item.get("relpath", "")
        reason = _escape_annotation(str(item.get("reason", "")))
        surface = _escape_annotation(str(item.get("surface", "")))
        annotations.append(f"::{annotation_level} file={relpath},title=Repo Agent protected proof surface::{surface}: {reason}")
    for check in verification.get("checks", []):
        if check.get("passed"):
            continue
        detail = _escape_annotation(str(check.get("detail", "")))
        invariant = _escape_annotation(str(check.get("id", "")))
        annotations.append(f"::error title=Repo Agent contract invariant failed::{invariant}: {detail}")
    return annotations


def _escape_annotation(value: str) -> str:
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A").replace(":", "%3A").replace(",", "%2C")


def _sarif_location(relpath: str) -> dict[str, Any]:
    uri = relpath or "proof-regression-contract.json"
    return {
        "physicalLocation": {
            "artifactLocation": {"uri": uri},
            "region": {"startLine": 1},
        }
    }


def _protected_surfaces(contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    surfaces: dict[str, dict[str, Any]] = {}
    target = dict(contract.get("target") or {})
    target_relpath = _normalize_relpath(str(target.get("relpath", "")))
    if target_relpath:
        surfaces[target_relpath] = {
            "surface": "proved_target_file",
            "reason": f"contains proved target {target.get('label', '')}",
        }
    for invariant in contract.get("invariants", []):
        if invariant.get("id") != "supporting_paths_exist":
            continue
        for path_item in invariant.get("paths", []):
            for label in path_item.get("path", []):
                relpath = _label_relpath(str(label))
                if relpath:
                    surfaces.setdefault(
                        relpath,
                        {
                            "surface": "proof_supporting_path",
                            "reason": "participates in route-to-target proof path",
                        },
                    )
    for route in (contract.get("proof_context") or {}).get("route_literals", []):
        for relpath, surface in list(surfaces.items()):
            if surface["surface"] == "proved_target_file":
                surfaces[relpath] = {
                    "surface": "route_exposed_target",
                    "reason": f"proved target is exposed through {route}",
                }
    return surfaces


def _matching_surfaces(relpath: str, surfaces: dict[str, dict[str, Any]]) -> list[tuple[str, str]]:
    matches = []
    for protected_path, item in surfaces.items():
        if relpath == protected_path or relpath.endswith(f"/{protected_path}"):
            matches.append((str(item.get("surface", "")), str(item.get("reason", ""))))
    return matches


def _label_relpath(label: str) -> str:
    if ":" not in label:
        return _normalize_relpath(label)
    return _normalize_relpath(label.split(":", 1)[0])


def _normalize_relpath(path: str) -> str:
    normalized = str(path).strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized
