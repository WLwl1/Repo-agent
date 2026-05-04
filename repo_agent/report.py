from __future__ import annotations

from html import escape
from pathlib import Path

from .models import AgentResult, FileFact, GraphEdge, RetrievalHit


def write_html_report(
    query: str,
    result: AgentResult,
    repo_stats: dict,
    file_facts: list[FileFact],
    output_path: Path,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    graph_svg = _build_graph_svg(result.hits, result.trace)
    file_rows = "\n".join(
        f"""
        <tr>
          <td>{escape(fact.relpath)}</td>
          <td>{escape(fact.language)}</td>
          <td>{fact.line_count}</td>
          <td>{len(fact.symbol_names)}</td>
          <td>{len(fact.routes)}</td>
          <td>{len(fact.imports)}</td>
          <td>{escape(", ".join(fact.roles[:4]))}</td>
        </tr>
        """
        for fact in file_facts[:12]
    )
    hit_cards = "\n".join(_render_hit_card(hit, index) for index, hit in enumerate(result.hits[:5], start=1))
    trace_items = "\n".join(
        f"""
        <article class="trace-item">
          <div class="trace-meta">Step {item.get('step', '?')} • {escape(item.get('type', 'trace'))}</div>
          <pre>{escape(str(item.get('content', '')))}</pre>
        </article>
        """
        for item in result.trace
    )
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Repo Agent Report</title>
  <style>
    :root {{
      --bg: #f5efe3;
      --panel: #fffaf2;
      --ink: #15212d;
      --muted: #556575;
      --line: #d8cbb8;
      --accent: #b84c2d;
      --accent-2: #1d5f73;
      --soft: #f0e2cd;
      --shadow: 0 18px 50px rgba(65, 44, 12, 0.12);
      --radius: 24px;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Segoe UI Variable", "Segoe UI", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(184, 76, 45, 0.12), transparent 24%),
        radial-gradient(circle at top right, rgba(29, 95, 115, 0.12), transparent 28%),
        linear-gradient(180deg, #f7f1e7 0%, #f2e8d8 100%);
    }}
    .page {{
      width: min(1380px, calc(100vw - 48px));
      margin: 24px auto 40px;
      display: grid;
      gap: 18px;
    }}
    .hero, .panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
    }}
    .hero {{
      padding: 28px;
      display: grid;
      gap: 14px;
      background:
        linear-gradient(135deg, rgba(184, 76, 45, 0.08), rgba(29, 95, 115, 0.07)),
        var(--panel);
    }}
    .hero h1 {{
      margin: 0;
      font-size: 40px;
      line-height: 1.05;
      letter-spacing: -0.03em;
    }}
    .hero p {{
      margin: 0;
      max-width: 820px;
      color: var(--muted);
      line-height: 1.7;
    }}
    .query {{
      padding: 14px 16px;
      border-radius: 16px;
      background: rgba(29, 95, 115, 0.08);
      border: 1px solid rgba(29, 95, 115, 0.16);
      font-family: Consolas, monospace;
    }}
    .stats {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 14px;
    }}
    .stat {{
      padding: 16px;
      border-radius: 18px;
      background: #fff;
      border: 1px solid var(--line);
    }}
    .stat label {{
      display: block;
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--muted);
      margin-bottom: 8px;
    }}
    .stat strong {{
      font-size: 28px;
    }}
    .grid {{
      display: grid;
      grid-template-columns: 1.1fr 0.9fr;
      gap: 18px;
    }}
    .panel {{
      padding: 22px;
    }}
    .panel h2 {{
      margin: 0 0 14px;
      font-size: 22px;
    }}
    .panel p {{
      color: var(--muted);
      line-height: 1.7;
    }}
    .hit-list {{
      display: grid;
      gap: 14px;
    }}
    .hit-card {{
      padding: 16px;
      border-radius: 18px;
      background: #fff;
      border: 1px solid var(--line);
    }}
    .hit-card header {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: center;
      margin-bottom: 10px;
    }}
    .rank {{
      width: 34px;
      height: 34px;
      border-radius: 999px;
      display: grid;
      place-items: center;
      background: var(--accent);
      color: white;
      font-weight: 700;
    }}
    .pill {{
      display: inline-flex;
      padding: 4px 9px;
      border-radius: 999px;
      background: rgba(29, 95, 115, 0.1);
      color: var(--accent-2);
      font-size: 12px;
      margin-right: 6px;
      margin-bottom: 6px;
    }}
    pre {{
      margin: 0;
      white-space: pre-wrap;
      word-break: break-word;
      line-height: 1.65;
      font-family: Consolas, monospace;
      font-size: 13px;
      color: var(--ink);
      background: #fff;
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 14px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 14px;
    }}
    th, td {{
      text-align: left;
      padding: 12px 10px;
      border-bottom: 1px solid var(--line);
    }}
    th {{
      font-size: 12px;
      text-transform: uppercase;
      color: var(--muted);
      letter-spacing: 0.08em;
    }}
    .trace-item {{
      margin-bottom: 12px;
    }}
    .trace-meta {{
      margin-bottom: 8px;
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }}
    .graph {{
      border: 1px dashed var(--line);
      border-radius: 20px;
      padding: 14px;
      background: rgba(240, 226, 205, 0.45);
    }}
    @media (max-width: 980px) {{
      .stats, .grid {{
        grid-template-columns: 1fr;
      }}
    }}
  </style>
</head>
<body>
  <main class="page">
    <section class="hero">
      <h1>Repo Agent Investigation Report</h1>
      <p>A visual analysis page for repository understanding, evidence ranking, and bug-localization demos.</p>
      <div class="query">{escape(query)}</div>
      <pre>{escape(result.repo_brief)}</pre>
      <div class="stats">
        <div class="stat"><label>Mode</label><strong>{escape(result.mode)}</strong></div>
        <div class="stat"><label>Files</label><strong>{repo_stats.get('file_count', 0)}</strong></div>
        <div class="stat"><label>Chunks</label><strong>{repo_stats.get('chunk_count', 0)}</strong></div>
        <div class="stat"><label>Graph Edges</label><strong>{repo_stats.get('graph_edge_count', 0)}</strong></div>
      </div>
    </section>
    <section class="grid">
      <section class="panel">
        <h2>Top Evidence</h2>
        <div class="hit-list">{hit_cards}</div>
      </section>
      <section class="panel">
        <h2>Repository Graph Slice</h2>
        <div class="graph">{graph_svg}</div>
        <h2 style="margin-top:18px;">Agent Answer</h2>
        <pre>{escape(result.answer)}</pre>
      </section>
    </section>
    <section class="grid">
      <section class="panel">
        <h2>Investigation Trace</h2>
        {trace_items}
      </section>
      <section class="panel">
        <h2>Repository Overview</h2>
        <table>
          <thead>
            <tr>
              <th>File</th>
              <th>Lang</th>
              <th>Lines</th>
              <th>Symbols</th>
              <th>Routes</th>
              <th>Imports</th>
              <th>Roles</th>
            </tr>
          </thead>
          <tbody>
            {file_rows}
          </tbody>
        </table>
      </section>
    </section>
  </main>
</body>
</html>
"""
    output_path.write_text(html, encoding="utf-8")
    return output_path


def _render_hit_card(hit: RetrievalHit, rank: int) -> str:
    reasons = "".join(f'<span class="pill">{escape(reason)}</span>' for reason in hit.reasons[:5])
    terms = "".join(f'<span class="pill">{escape(term)}</span>' for term in hit.matched_terms[:6])
    return f"""
    <article class="hit-card">
      <header>
        <div style="display:flex;align-items:center;gap:12px;">
          <div class="rank">{rank}</div>
          <div>
            <strong>{escape(hit.chunk.source_label)}</strong><br>
            <span style="color:#556575;">Lines {hit.chunk.start_line}-{hit.chunk.end_line} • Score {hit.score:.2f}</span>
          </div>
        </div>
      </header>
      <div style="margin-bottom:10px;">{reasons}</div>
      <div style="margin-bottom:10px;">{terms}</div>
      <pre>{escape(_trim_snippet(hit.chunk.text, 16))}</pre>
    </article>
    """


def _build_graph_svg(hits: list[RetrievalHit], trace: list[dict]) -> str:
    if not hits:
        return "<p>No graph slice available.</p>"
    width = 560
    height = 120 + len(hits[:5]) * 92
    nodes = hits[:5]
    node_positions = {}
    node_markup: list[str] = []
    edge_markup: list[str] = []
    for index, hit in enumerate(nodes):
        x = 40 + (index % 2) * 250
        y = 40 + index * 78
        node_positions[hit.chunk.source_label] = (x, y)
        node_markup.append(
            f'<rect x="{x}" y="{y}" rx="18" ry="18" width="210" height="52" fill="#fffaf2" stroke="#b84c2d" stroke-width="1.5"></rect>'
        )
        node_markup.append(
            f'<text x="{x + 14}" y="{y + 22}" font-size="13" font-family="Segoe UI, sans-serif" fill="#15212d">{escape(_truncate(hit.chunk.source_label, 28))}</text>'
        )
        node_markup.append(
            f'<text x="{x + 14}" y="{y + 39}" font-size="11" font-family="Segoe UI, sans-serif" fill="#556575">score {hit.score:.2f}</text>'
        )

    graph_lines = []
    for item in trace:
        if item.get("type") in {"graph_expansion", "graph_hop"}:
            graph_lines = [line.strip() for line in str(item.get("content", "")).splitlines() if "->" in line]
            break
    for line in graph_lines[:6]:
        left, _, right = line.partition("->")
        source = left.strip()
        target = right.split("(", 1)[0].strip()
        if source in node_positions and target in node_positions:
            sx, sy = node_positions[source]
            tx, ty = node_positions[target]
            edge_markup.append(
                f'<line x1="{sx + 210}" y1="{sy + 26}" x2="{tx}" y2="{ty + 26}" stroke="#1d5f73" stroke-width="2"></line>'
            )

    return (
        f'<svg width="100%" viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg">'
        + "".join(edge_markup)
        + "".join(node_markup)
        + "</svg>"
    )


def _trim_snippet(text: str, max_lines: int) -> str:
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return text.strip()
    return "\n".join(lines[:max_lines]).strip() + "\n..."


def _truncate(text: str, max_length: int) -> str:
    if len(text) <= max_length:
        return text
    return text[: max_length - 3] + "..."
