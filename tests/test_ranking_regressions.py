from __future__ import annotations

from pathlib import Path

from repo_agent.indexer import build_index


def test_style_intent_prefers_css_without_assuming_web_directory(tmp_path: Path) -> None:
    (tmp_path / "assets").mkdir()
    (tmp_path / "pages").mkdir()
    (tmp_path / "assets" / "theme.css").write_text(
        ":root { --accent: teal; }\n.dashboard { color: var(--accent); }\n",
        encoding="utf-8",
    )
    (tmp_path / "pages" / "dashboard.html").write_text(
        '<link rel="stylesheet" href="../assets/theme.css">\n<div class="dashboard"></div>\n',
        encoding="utf-8",
    )
    (tmp_path / "pages" / "dashboard.js").write_text(
        "export function renderDashboard() { return 'dashboard'; }\n",
        encoding="utf-8",
    )

    result = build_index(tmp_path).investigate("Where are the CSS styles for the dashboard?", top_k=3)

    assert result.final_hits
    assert result.final_hits[0].chunk.relpath == "assets/theme.css"
    assert "stylesheet intent" in result.final_hits[0].reasons
