from __future__ import annotations

from html import escape
from pathlib import Path

from .models import AgentResult, FileFact, RetrievalHit


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
    diagnostics = _render_diagnostics(result)
    graph_audit = _render_graph_search_audit(result)
    proof_panel = _render_proof_panel(result)
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
    .muted {{
      color: var(--muted);
      line-height: 1.5;
    }}
    .diagnostics {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
      margin-top: 4px;
    }}
    .diagnostics > div {{
      background: #fff;
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 14px;
      min-width: 0;
    }}
    .diagnostics label {{
      display: block;
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--muted);
      margin-bottom: 6px;
    }}
    .diagnostics strong {{
      font-size: 20px;
    }}
    .diagnostics span {{
      color: var(--ink);
      line-height: 1.5;
    }}
    .diagnostics ul {{
      margin: 0;
      padding-left: 18px;
      color: var(--ink);
      line-height: 1.5;
    }}
    .graph-audit {{
      margin-top: 18px;
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
    }}
    .graph-audit-card {{
      background: #fff;
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 14px;
      min-width: 0;
    }}
    .graph-audit-card strong {{
      display: block;
      margin-bottom: 6px;
      overflow-wrap: anywhere;
    }}
    .graph-audit-card small {{
      color: var(--muted);
      display: block;
      line-height: 1.5;
    }}
    .proof-panel {{
      margin-top: 18px;
      padding: 16px;
      border: 1px solid var(--line);
      border-radius: 18px;
      background: #fff;
    }}
    .proof-panel ul {{
      margin: 10px 0 0;
      padding-left: 18px;
      line-height: 1.6;
    }}
    .proof-panel code {{
      background: rgba(240, 226, 205, 0.7);
      padding: 2px 5px;
      border-radius: 6px;
    }}
    .decoy-audit {{
      margin-top: 14px;
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
    }}
    .decoy-card {{
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 12px;
      background: #fff7f5;
      min-width: 0;
    }}
    .decoy-card strong,
    .decoy-card small {{
      display: block;
      overflow-wrap: anywhere;
    }}
    .decoy-card small {{
      color: var(--muted);
      line-height: 1.45;
      margin-top: 5px;
    }}
    .proof-graph {{
      margin-top: 14px;
      border: 1px dashed var(--line);
      border-radius: 16px;
      background: rgba(240, 226, 205, 0.32);
      overflow-x: auto;
    }}
    .proof-graph svg {{
      display: block;
      min-width: 720px;
    }}
    @media (max-width: 980px) {{
      .stats, .grid, .diagnostics, .graph-audit {{
        grid-template-columns: 1fr;
      }}
      .decoy-audit {{
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
      {diagnostics}
      {graph_audit}
      {proof_panel}
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


def _render_diagnostics(result: AgentResult) -> str:
    diagnostics = result.diagnostics
    if diagnostics is None:
        return ""
    strengths = "".join(f"<li>{escape(item)}</li>" for item in diagnostics.strengths[:5])
    warnings = "".join(f"<li>{escape(item)}</li>" for item in diagnostics.warnings[:5])
    terms = ", ".join(diagnostics.matched_terms[:8]) or "none"
    return f"""
      <section class="diagnostics">
        <div>
          <label>Evidence Confidence</label>
          <strong>{escape(diagnostics.label)} · {diagnostics.confidence:.2f}</strong>
        </div>
        <div>
          <label>Coverage</label>
          <span>{diagnostics.evidence_count} hits · {diagnostics.unique_files} files · {diagnostics.graph_edge_count} graph edges</span>
        </div>
        <div>
          <label>Score Shape</label>
          <span>top {diagnostics.top_score:.2f} · gap {diagnostics.score_gap:.2f}</span>
        </div>
        <div>
          <label>Matched Terms</label>
          <span>{escape(terms)}</span>
        </div>
        <div>
          <label>Strengths</label>
          <ul>{strengths or "<li>none</li>"}</ul>
        </div>
        <div>
          <label>Warnings</label>
          <ul>{warnings or "<li>none</li>"}</ul>
        </div>
      </section>
    """


def _render_graph_search_audit(result: AgentResult) -> str:
    graph_search = result.graph_search or {}
    top_visited = list(graph_search.get("top_visited") or [])
    if not top_visited:
        return ""
    cards = []
    for item in top_visited[:6]:
        path = " -> ".join(str(label) for label in item.get("path", [])[:5]) or "none"
        cards.append(
            f"""
            <article class="graph-audit-card">
              <strong>{escape(str(item.get('chunk', '')))}</strong>
              <small>
                visits {int(item.get('visits', 0))} &middot;
                reward {float(item.get('average_reward', 0.0)):.3f} &middot;
                boost +{float(item.get('boost', 0.0)):.2f}
              </small>
              <small>path {escape(path)}</small>
            </article>
            """
        )
    return f"""
      <section>
        <h2>Graph Search Audit</h2>
        <p class="muted">
          graph_mcts &middot; iterations {int(graph_search.get('iterations', 0))}
          &middot; depth {int(graph_search.get('max_depth', 0))}
          &middot; visited {int(graph_search.get('visited_count', 0))}
        </p>
        <div class="graph-audit">{''.join(cards)}</div>
      </section>
    """


def _render_proof_panel(result: AgentResult) -> str:
    proof = result.proof or {}
    if not proof:
        return ""
    checks = "".join(
        (
            f"<li><code>{escape(str(item.get('name', 'check')))}</code> "
            f"{'PASS' if item.get('passed') else 'FAIL'} - {escape(str(item.get('detail', '')))}</li>"
        )
        for item in proof.get("checks", [])[:6]
    )
    paths = "".join(
        (
            f"<li><code>{escape(str(item.get('route', '')))}</code> "
            f"depth {int(item.get('depth', 0))} "
            f"boost +{float(item.get('boost', 0.0)):.2f}: "
            f"{escape(' -> '.join(str(label) for label in item.get('path', [])))}</li>"
        )
        for item in proof.get("supporting_paths", [])[:4]
    )
    proof_graph = _build_proof_graph_svg(dict(proof.get("proof_graph") or {}))
    decoy_audit = _render_decoy_audit(list(proof.get("decoy_audit") or []))
    return f"""
      <section class="proof-panel">
        <h2>Proof-Carrying Retrieval</h2>
        <p class="muted">
          status <code>{escape(str(proof.get('status', 'unknown')))}</code>
          &middot; strategy <code>{escape(str(proof.get('strategy', '')))}</code>
        </p>
        <p>{escape(str(proof.get('claim', '')))}</p>
        <ul>{checks or '<li>No proof checks recorded.</li>'}</ul>
        <ul>{paths or '<li>No route-anchored supporting path recorded.</li>'}</ul>
        {decoy_audit}
        {proof_graph}
      </section>
    """


def _render_decoy_audit(decoys: list[dict]) -> str:
    if not decoys:
        return ""
    cards = []
    for item in decoys[:6]:
        roles = ", ".join(str(role) for role in item.get("conflicting_roles", [])) or "none"
        routes = ", ".join(str(route) for route in item.get("requested_routes", [])) or "none"
        cards.append(
            f"""
            <article class="decoy-card">
              <strong>{escape(str(item.get('candidate', '')))}</strong>
              <small>
                rejected {str(bool(item.get('rejected'))).lower()} &middot;
                gap {float(item.get('score_gap', 0.0)):.2f} &middot;
                route anchored {str(bool(item.get('route_anchored'))).lower()}
              </small>
              <small>roles {escape(roles)} &middot; requested {escape(routes)}</small>
              <small>{escape(str(item.get('reason', '')))}</small>
            </article>
            """
        )
    return f"""
      <h3>Contrastive Decoy Audit</h3>
      <div class="decoy-audit">{''.join(cards)}</div>
    """


def _build_proof_graph_svg(proof_graph: dict) -> str:
    nodes = list(proof_graph.get("nodes") or [])[:10]
    edges = list(proof_graph.get("edges") or [])[:14]
    if not nodes:
        return ""
    width = 760
    height = max(260, 90 + len(nodes) * 42)
    positions: dict[str, tuple[int, int]] = {}
    for index, node in enumerate(nodes):
        roles = set(node.get("roles") or [])
        if "route_anchor" in roles:
            x = 36
        elif "top_hit" in roles:
            x = 292
        elif "decoy" in roles:
            x = 548
        else:
            x = 292 if index % 2 else 164
        y = 42 + index * 42
        positions[str(node.get("id", ""))] = (x, y)

    edge_markup = []
    for edge in edges:
        source = str(edge.get("source", ""))
        target = str(edge.get("target", ""))
        if source not in positions or target not in positions:
            continue
        sx, sy = positions[source]
        tx, ty = positions[target]
        color = "#1d5f73" if edge.get("label") in {"route_path", "anchors"} else "#9b7a55"
        edge_markup.append(
            f'<path d="M {sx + 148} {sy + 16} C {sx + 210} {sy + 16}, {tx - 42} {ty + 16}, {tx} {ty + 16}" '
            f'fill="none" stroke="{color}" stroke-width="1.2" opacity="0.62"></path>'
        )
        edge_markup.append(
            f'<text x="{(sx + tx) / 2 + 54:.0f}" y="{(sy + ty) / 2 + 10:.0f}" '
            f'font-size="10" font-family="Segoe UI, sans-serif" fill="{color}">{escape(str(edge.get("label", "")))}</text>'
        )

    node_markup = []
    for node in nodes:
        node_id = str(node.get("id", ""))
        x, y = positions[node_id]
        roles = set(node.get("roles") or [])
        fill = "#eef7f2"
        stroke = "#1d5f73"
        if "route_anchor" in roles:
            fill = "#eaf4ff"
            stroke = "#2f6fb0"
        elif "top_hit" in roles:
            fill = "#fff3df"
            stroke = "#b84c2d"
        elif "decoy" in roles:
            fill = "#fff1f1"
            stroke = "#a94b58"
        role_label = ", ".join(str(role) for role in node.get("roles", [])[:2])
        score = f"score {float(node.get('score')):.2f}" if node.get("score") is not None else role_label
        node_markup.append(
            f'<rect x="{x}" y="{y}" rx="10" ry="10" width="150" height="34" fill="{fill}" '
            f'stroke="{stroke}" stroke-width="1.4"></rect>'
        )
        node_markup.append(
            f'<text x="{x + 9}" y="{y + 14}" font-size="11" font-family="Segoe UI, sans-serif" fill="#15212d">'
            f'{escape(_truncate(node_id, 22))}</text>'
        )
        node_markup.append(
            f'<text x="{x + 9}" y="{y + 28}" font-size="9" font-family="Segoe UI, sans-serif" fill="#556575">'
            f'{escape(_truncate(score, 24))}</text>'
        )

    return f"""
      <div class="proof-graph" aria-label="Proof graph">
        <svg width="100%" viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg">
          <text x="36" y="24" font-size="12" font-family="Segoe UI, sans-serif" fill="#556575">route anchors</text>
          <text x="292" y="24" font-size="12" font-family="Segoe UI, sans-serif" fill="#556575">supporting path / top hit</text>
          <text x="548" y="24" font-size="12" font-family="Segoe UI, sans-serif" fill="#556575">decoy candidates</text>
          {''.join(edge_markup)}
          {''.join(node_markup)}
        </svg>
      </div>
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
