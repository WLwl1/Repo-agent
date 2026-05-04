from __future__ import annotations

from pathlib import Path

from repo_agent.server import _resolve_static_dir


def test_static_assets_resolve_from_source_tree() -> None:
    project_root = Path(__file__).resolve().parents[1]

    static_dir = _resolve_static_dir(project_root)

    assert (static_dir / "index.html").is_file()
    assert (static_dir / "app.js").is_file()
    assert (static_dir / "styles.css").is_file()

