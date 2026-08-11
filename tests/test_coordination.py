from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from repo_agent.__main__ import build_coordination_status, render_coordination_markdown


def test_coordination_status_parses_claims_and_dirty_claimed_files(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    subprocess.run(["git", "-C", str(repo_root), "init"], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(repo_root), "config", "user.email", "repo-agent@example.local"], check=True)
    subprocess.run(["git", "-C", str(repo_root), "config", "user.name", "Repo Agent"], check=True)
    (repo_root / ".agents").mkdir()
    (repo_root / "repo_agent").mkdir()
    (repo_root / "repo_agent" / "proof.py").write_text("VALUE = 1\n", encoding="utf-8")
    (repo_root / ".agents" / "coordination.md").write_text(
        """
# Repo Agent Multi-Session Coordination

## Active Claims

| Session | Focus | Files Claimed | Status |
| --- | --- | --- | --- |
| alpha | Proof reliability | `repo_agent/proof.py`, `tests/test_proof.py` | active |
| beta | UX reporting | `web/app.js` | done |
""".strip(),
        encoding="utf-8",
    )
    subprocess.run(["git", "-C", str(repo_root), "add", "."], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(repo_root), "commit", "-m", "baseline"], check=True, capture_output=True, text=True)
    (repo_root / "repo_agent" / "proof.py").write_text("VALUE = 2\n", encoding="utf-8")

    payload = build_coordination_status(repo_root, stale_minutes=120)
    markdown = render_coordination_markdown(payload)

    assert payload["strategy"] == "multi_session_coordination_status"
    assert payload["active_claims"][0]["session"] == "alpha"
    assert payload["dirty_file_count"] == 1
    assert payload["claims_touching_dirty_files"][0]["file"] == "repo_agent/proof.py"
    assert "# Repo Agent Coordination Status" in markdown
    assert "Dirty Claimed Files" in markdown


def test_coordination_status_reports_overlapping_active_claims(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / ".agents").mkdir()
    (repo_root / ".agents" / "coordination.md").write_text(
        """
| Session | Focus | Files Claimed | Status |
| --- | --- | --- | --- |
| alpha | Proof | `repo_agent/proof.py` | active |
| beta | Replay | `repo_agent/proof.py` | active |
""".strip(),
        encoding="utf-8",
    )

    payload = build_coordination_status(repo_root, stale_minutes=120)

    assert payload["claim_conflicts"] == [{"file": "repo_agent/proof.py", "sessions": ["alpha", "beta"]}]
    assert any("overlap" in warning for warning in payload["warnings"])


def test_coordination_cli_prints_json() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "repo_agent", "coordination", "--json"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["strategy"] == "multi_session_coordination_status"
    assert "active_claims" in payload
