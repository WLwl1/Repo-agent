from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape


ROOT = Path(__file__).resolve().parents[1]
SVG_OUT = ROOT / "assets" / "repo-agent-publication-architecture.svg"

W, H = 2400, 1350

P = {
    "paper": "#FFFFFF",
    "ink": "#172033",
    "muted": "#667085",
    "hair": "#CBD5E1",
    "soft": "#F8FAFC",
    "blue": "#356FA3",
    "blue_soft": "#EEF5FB",
    "orange": "#D9823C",
    "orange_soft": "#FFF5EA",
    "teal": "#338B7A",
    "teal_soft": "#ECF8F4",
    "purple": "#7563A8",
    "purple_soft": "#F3F0FA",
    "red": "#B55454",
    "red_soft": "#FBEEEE",
}


def esc(value: object) -> str:
    return escape(str(value))


def rect(x: float, y: float, w: float, h: float, *, fill: str = "#FFFFFF", stroke: str = P["hair"], width: float = 1.5, radius: float = 14) -> str:
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{radius}" fill="{fill}" stroke="{stroke}" stroke-width="{width}"/>'


def line(x1: float, y1: float, x2: float, y2: float, *, color: str = P["ink"], width: float = 2.2, dashed: bool = False, arrow: bool = True) -> str:
    dash = ' stroke-dasharray="10 8"' if dashed else ""
    marker = ' marker-end="url(#arrow-muted)"' if arrow and color == P["muted"] else (' marker-end="url(#arrow)"' if arrow else "")
    return f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="{width}" stroke-linecap="round"{dash}{marker}/>'


def path(points: list[tuple[float, float]], *, color: str = P["ink"], width: float = 2.2, dashed: bool = False, arrow: bool = True) -> str:
    d = "M " + " L ".join(f"{x} {y}" for x, y in points)
    dash = ' stroke-dasharray="10 8"' if dashed else ""
    marker = ' marker-end="url(#arrow-muted)"' if arrow and color == P["muted"] else (' marker-end="url(#arrow)"' if arrow else "")
    return f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{width}" stroke-linecap="round" stroke-linejoin="round"{dash}{marker}/>'


def text(x: float, y: float, value: str, *, size: int = 18, weight: int = 400, color: str = P["ink"], anchor: str = "start", family: str = "Inter, Arial, Helvetica, sans-serif", letter_spacing: float | None = None) -> str:
    spacing = f' letter-spacing="{letter_spacing}"' if letter_spacing is not None else ""
    return f'<text x="{x}" y="{y}" font-family="{family}" font-size="{size}" font-weight="{weight}" fill="{color}" text-anchor="{anchor}"{spacing}>{esc(value)}</text>'


def multiline(x: float, y: float, lines: list[str], *, size: int = 18, weight: int = 400, color: str = P["ink"], anchor: str = "start", leading: float = 1.35, family: str = "Inter, Arial, Helvetica, sans-serif") -> str:
    parts = [f'<text x="{x}" y="{y}" font-family="{family}" font-size="{size}" font-weight="{weight}" fill="{color}" text-anchor="{anchor}">']
    for index, value in enumerate(lines):
        dy = 0 if index == 0 else size * leading
        parts.append(f'<tspan x="{x}" dy="{dy}">{esc(value)}</tspan>')
    parts.append("</text>")
    return "".join(parts)


def pill(x: float, y: float, w: float, label: str, *, fill: str, color: str, stroke: str | None = None, h: float = 38, size: int = 15) -> list[str]:
    return [
        rect(x, y, w, h, fill=fill, stroke=stroke or color, width=1.1, radius=h / 2),
        text(x + w / 2, y + h / 2 + 5, label, size=size, weight=600, color=color, anchor="middle"),
    ]


def panel_header(parts: list[str], x: float, y: float, label: str, title_value: str, color: str) -> None:
    parts.append(text(x, y, label, size=19, weight=700, color=color, family="Georgia, Times New Roman, serif"))
    parts.append(text(x + 42, y, title_value, size=25, weight=700, family="Georgia, Times New Roman, serif"))


def card(parts: list[str], x: float, y: float, w: float, h: float, title_value: str, subtitle: str, *, accent: str, fill: str = "#FFFFFF") -> None:
    parts.append(rect(x, y, w, h, fill=fill, stroke=P["hair"], width=1.4, radius=13))
    parts.append(f'<rect x="{x}" y="{y}" width="7" height="{h}" rx="3.5" fill="{accent}"/>')
    parts.append(text(x + 28, y + 38, title_value, size=19, weight=700))
    parts.append(text(x + 28, y + 66, subtitle, size=15, color=P["muted"]))


def render() -> str:
    s: list[str] = [
        f'<svg width="{W}" height="{H}" viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg">',
        "<defs>",
        f'<marker id="arrow" markerWidth="10" markerHeight="10" refX="8" refY="5" orient="auto" markerUnits="strokeWidth"><path d="M0,0 L10,5 L0,10 z" fill="{P["ink"]}"/></marker>',
        f'<marker id="arrow-muted" markerWidth="10" markerHeight="10" refX="8" refY="5" orient="auto" markerUnits="strokeWidth"><path d="M0,0 L10,5 L0,10 z" fill="{P["muted"]}"/></marker>',
        '<filter id="shadow" x="-10%" y="-10%" width="120%" height="120%"><feDropShadow dx="0" dy="3" stdDeviation="5" flood-color="#172033" flood-opacity="0.08"/></filter>',
        "</defs>",
        f'<rect width="{W}" height="{H}" fill="{P["paper"]}"/>',
        text(72, 72, "REPO AGENT", size=16, weight=800, color=P["blue"], letter_spacing=2.4),
        text(72, 118, "Evidence-first repository localization with replayable proofs", size=34, weight=700, family="Georgia, Times New Roman, serif"),
        text(72, 154, "A deterministic evidence layer identifies where to inspect, why the evidence is relevant, and whether it still holds after code changes.", size=17, color=P["muted"]),
    ]

    # Main panels.
    panels = [
        (62, 205, 515, 1015, P["orange_soft"]),
        (605, 205, 1165, 1015, P["blue_soft"]),
        (1798, 205, 540, 1015, P["teal_soft"]),
    ]
    for x, y, w, h, fill in panels:
        s.append(rect(x, y, w, h, fill=fill, stroke=P["hair"], width=1.5, radius=18))

    panel_header(s, 92, 252, "(a)", "Typed repository evidence", P["orange"])
    panel_header(s, 635, 252, "(b)", "Evidence-guided localization", P["blue"])
    panel_header(s, 1828, 252, "(c)", "Replayable decision evidence", P["teal"])

    # Panel A: evidence construction.
    card(s, 122, 315, 395, 100, "Local codebase", "source files, routes, configs, tests", accent=P["orange"])
    s.append(line(320, 415, 320, 470, color=P["muted"]))
    card(s, 122, 470, 395, 112, "Static parsing", "Python AST · Tree-sitter · safe fallback", accent=P["orange"])
    s.append(line(320, 582, 320, 637, color=P["muted"]))

    s.append(rect(100, 637, 440, 425, fill="#FFFFFF", stroke=P["hair"], width=1.4, radius=16))
    s.append(text(130, 681, "RepositoryIndex", size=22, weight=700))
    s.append(text(130, 710, "typed, inspectable, cacheable", size=15, color=P["muted"]))
    rows = [
        ("Content chunks", "implementation text + line ranges", P["orange"]),
        ("Identifiers & paths", "symbols, qualified names, file roles", P["blue"]),
        ("Structure facts", "routes, calls, imports, references", P["purple"]),
        ("Repository graph", "typed weighted edges", P["teal"]),
    ]
    for index, (name, body, color) in enumerate(rows):
        yy = 752 + index * 70
        s.append(f'<circle cx="146" cy="{yy}" r="7" fill="{color}"/>')
        s.append(text(168, yy + 6, name, size=17, weight=650))
        s.append(text(168, yy + 30, body, size=14, color=P["muted"]))
    s.extend(pill(122, 1090, 178, "model-optional", fill=P["soft"], color=P["muted"], stroke=P["hair"]))
    s.extend(pill(315, 1090, 202, "local & deterministic", fill=P["soft"], color=P["muted"], stroke=P["hair"]))

    # Bridge from index to retrieval.
    s.append(path([(540, 845), (622, 845), (622, 620), (665, 620)], color=P["muted"], width=2.2))
    s.append(text(585, 872, "typed evidence", size=13, color=P["muted"], anchor="middle"))

    # Panel B: query and plan.
    s.append(rect(750, 305, 870, 76, fill="#FFFFFF", stroke=P["hair"], width=1.4, radius=14))
    s.append(text(1185, 338, "Repository question / bug report", size=20, weight=700, anchor="middle"))
    s.append(text(1185, 365, '"Which function writes streamed tokens for the public /api/chat route?"', size=15, color=P["muted"], anchor="middle"))
    s.append(line(1185, 381, 1185, 420, color=P["muted"]))
    s.append(rect(930, 420, 510, 76, fill="#FFFFFF", stroke=P["hair"], width=1.4, radius=14))
    s.append(text(1185, 451, "Query plan", size=19, weight=700, anchor="middle"))
    s.append(text(1185, 478, "intent · action · route literal · target role", size=15, color=P["muted"], anchor="middle"))
    s.append(path([(1185, 496), (1185, 530), (850, 530), (850, 565)], color=P["muted"]))

    # Retrieval stage.
    s.append(rect(665, 565, 330, 455, fill="#FFFFFF", stroke=P["hair"], width=1.4, radius=16))
    s.append(text(695, 608, "1  Multi-view retrieval", size=20, weight=700, color=P["blue"]))
    s.append(text(695, 636, "Independent relevance surfaces", size=14, color=P["muted"]))
    views = [
        ("Content", "implementation text", P["orange_soft"], P["orange"]),
        ("Identifier", "symbol + calls", P["blue_soft"], P["blue"]),
        ("Path", "file + language", P["purple_soft"], P["purple"]),
        ("Structure", "route + imports", P["teal_soft"], P["teal"]),
    ]
    for index, (name, body, fill, color) in enumerate(views):
        yy = 674 + index * 65
        s.append(rect(695, yy, 270, 52, fill=fill, stroke=color, width=1.0, radius=9))
        s.append(text(715, yy + 24, name, size=16, weight=700, color=color))
        s.append(text(945, yy + 24, body, size=13, color=P["muted"], anchor="end"))
    s.append(line(830, 921, 830, 945, color=P["muted"]))
    s.append(rect(730, 945, 200, 50, fill=P["blue"], stroke=P["blue"], width=1, radius=25))
    s.append(text(830, 977, "Weighted RRF", size=16, weight=700, color="#FFFFFF", anchor="middle"))

    # Graph stage.
    s.append(line(995, 790, 1030, 790, color=P["muted"]))
    s.append(rect(1030, 565, 330, 455, fill="#FFFFFF", stroke=P["hair"], width=1.4, radius=16))
    s.append(text(1060, 608, "2  Graph diffusion", size=20, weight=700, color=P["purple"]))
    s.append(text(1060, 636, "Bounded Personalized PageRank", size=14, color=P["muted"]))

    # Mini graph with clean edges.
    graph_edges = [
        ((1100, 750), (1195, 700)),
        ((1195, 700), (1285, 750)),
        ((1195, 700), (1195, 820)),
        ((1100, 750), (1125, 875)),
        ((1285, 750), (1260, 875)),
    ]
    for (x1, y1), (x2, y2) in graph_edges:
        s.append(line(x1, y1, x2, y2, color=P["hair"], width=2, arrow=False))
    nodes = [
        (1100, 750, "route", P["orange"]),
        (1195, 700, "handler", P["blue"]),
        (1285, 750, "call", P["purple"]),
        (1195, 820, "writer", P["teal"]),
        (1125, 875, "import", P["muted"]),
        (1260, 875, "decoy", P["red"]),
    ]
    for cx, cy, label, color in nodes:
        s.append(f'<circle cx="{cx}" cy="{cy}" r="24" fill="#FFFFFF" stroke="{color}" stroke-width="3"/>')
        s.append(text(cx, cy + 45, label, size=13, color=color, anchor="middle"))
    s.extend(pill(1070, 945, 250, "route-anchored restart", fill=P["purple_soft"], color=P["purple"], stroke=P["purple"]))

    # Decision stage.
    s.append(line(1360, 790, 1395, 790, color=P["muted"]))
    s.append(rect(1395, 565, 330, 455, fill="#FFFFFF", stroke=P["hair"], width=1.4, radius=16))
    s.append(text(1425, 608, "3  Evidence decision", size=20, weight=700, color=P["teal"]))
    s.append(text(1425, 636, "Interpretable reranking", size=14, color=P["muted"]))
    decisions = [
        ("Intent alignment", "entry vs. handler vs. writer", P["blue"]),
        ("Path support", "route-reachable evidence", P["purple"]),
        ("Contrastive audit", "admin · legacy · mock", P["red"]),
    ]
    for index, (name, body, color) in enumerate(decisions):
        yy = 690 + index * 82
        s.append(f'<circle cx="1440" cy="{yy}" r="6" fill="{color}"/>')
        s.append(text(1460, yy + 5, name, size=16, weight=700))
        s.append(text(1460, yy + 30, body, size=14, color=P["muted"]))
    s.append(rect(1430, 945, 260, 50, fill=P["teal"], stroke=P["teal"], width=1, radius=25))
    s.append(text(1560, 977, "Ranked evidence state", size=16, weight=700, color="#FFFFFF", anchor="middle"))

    # Panel C: horizontal handoff and proof.
    s.append(line(1725, 790, 1840, 790, color=P["muted"]))
    s.append(rect(1840, 315, 456, 402, fill="#FFFFFF", stroke=P["hair"], width=1.4, radius=16))
    s.append(text(1872, 360, "Proof-carrying retrieval", size=21, weight=700, color=P["teal"]))
    s.append(text(1872, 389, "A compact, machine-readable evidence contract", size=14, color=P["muted"]))
    s.append(text(1872, 438, "Top hit", size=14, weight=700, color=P["muted"]))
    s.append(rect(1872, 455, 392, 58, fill=P["teal_soft"], stroke=P["teal"], width=1.0, radius=10))
    s.append(text(1894, 490, "server.js:writeChatDelta", size=16, weight=700, color=P["teal"]))
    s.append(text(1872, 552, "Supporting execution path", size=14, weight=700, color=P["muted"]))

    path_y = 603
    proof_nodes = [
        (1892, "/api/chat", P["orange"]),
        (1997, "handler", P["blue"]),
        (2099, "stream", P["purple"]),
        (2200, "writer", P["teal"]),
    ]
    for index, (cx, label, color) in enumerate(proof_nodes):
        if index:
            previous_x = proof_nodes[index - 1][0]
            s.append(line(previous_x + 25, path_y, cx - 25, path_y, color=P["hair"], width=2, arrow=False))
        s.append(f'<circle cx="{cx}" cy="{path_y}" r="22" fill="#FFFFFF" stroke="{color}" stroke-width="3"/>')
        s.append(text(cx, path_y + 47, label, size=12, color=color, anchor="middle"))
    s.extend(pill(1872, 665, 166, "status: proved", fill=P["teal_soft"], color=P["teal"], stroke=P["teal"]))
    s.extend(pill(2052, 665, 212, "warnings: none", fill=P["soft"], color=P["muted"], stroke=P["hair"]))

    # Replay / decoy boxes.
    s.append(rect(1840, 755, 214, 142, fill="#FFFFFF", stroke=P["hair"], width=1.3, radius=13))
    s.append(text(1866, 796, "Strict replay", size=18, weight=700, color=P["purple"]))
    s.append(multiline(1866, 828, ["re-check nodes,", "paths, and graph edges"], size=14, color=P["muted"]))
    s.append(rect(2082, 755, 214, 142, fill="#FFFFFF", stroke=P["hair"], width=1.3, radius=13))
    s.append(text(2108, 796, "Decoy audit", size=18, weight=700, color=P["red"]))
    s.append(multiline(2108, 828, ["surface tempting", "hard negatives"], size=14, color=P["muted"]))
    s.append(path([(2068, 717), (2068, 735), (1947, 735), (1947, 755)], color=P["hair"], width=1.8))
    s.append(path([(2068, 735), (2189, 735), (2189, 755)], color=P["hair"], width=1.8))

    s.append(text(1840, 950, "Reviewable outputs", size=17, weight=700))
    outputs = [
        ("Grounded answer", P["blue_soft"], P["blue"]),
        ("Evidence report", P["orange_soft"], P["orange"]),
        ("Portable bundle", P["teal_soft"], P["teal"]),
    ]
    for index, (label, fill, color) in enumerate(outputs):
        yy = 975 + index * 62
        s.append(rect(1840, yy, 456, 46, fill=fill, stroke=color, width=1.0, radius=10))
        s.append(text(2068, yy + 29, label, size=15, weight=650, color=color, anchor="middle"))

    # Bottom claim strip.
    s.append(rect(62, 1245, 2276, 66, fill=P["soft"], stroke=P["hair"], width=1.2, radius=14))
    claims = [
        ("LOCAL", "no model required", P["orange"]),
        ("STRUCTURAL", "route / call / import", P["blue"]),
        ("REPLAYABLE", "evidence can expire", P["purple"]),
        ("FALSIFIABLE", "failures remain visible", P["teal"]),
    ]
    claim_x = [120, 670, 1220, 1770]
    for x, (title_value, body, color) in zip(claim_x, claims, strict=True):
        s.append(text(x, 1278, title_value, size=14, weight=800, color=color, letter_spacing=1.3))
        s.append(text(x + 118, 1278, body, size=15, color=P["muted"]))

    s.append("</svg>")
    return "\n".join(s) + "\n"


if __name__ == "__main__":
    SVG_OUT.write_text(render(), encoding="utf-8")
    print(SVG_OUT)
