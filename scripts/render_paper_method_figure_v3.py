# -*- coding: utf-8 -*-
from pathlib import Path
from xml.sax.saxutils import escape

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
PNG_OUT = ROOT / "assets" / "repo-agent-paper-method-figure-v3.png"
SVG_OUT = ROOT / "assets" / "repo-agent-paper-method-figure-v3.svg"

W, H = 2200, 1240


PALETTE = {
    "paper": "#FFFFFF",
    "ink": "#111827",
    "muted": "#4B5563",
    "light": "#F8FAFC",
    "line": "#111827",
    "soft_line": "#9CA3AF",
    "blue": "#1D4ED8",
    "blue_soft": "#EFF6FF",
    "amber": "#B45309",
    "amber_soft": "#FFF7ED",
    "green": "#047857",
    "green_soft": "#ECFDF5",
    "violet": "#6D28D9",
    "violet_soft": "#F5F3FF",
    "gray_soft": "#F3F4F6",
}


def pick_font(size, bold=False, mono=False, serif=False):
    if mono:
        candidates = [
            "C:/Windows/Fonts/consolab.ttf" if bold else "C:/Windows/Fonts/consola.ttf",
            "C:/Windows/Fonts/courbd.ttf" if bold else "C:/Windows/Fonts/cour.ttf",
        ]
    elif serif:
        candidates = [
            "C:/Windows/Fonts/timesbd.ttf" if bold else "C:/Windows/Fonts/times.ttf",
            "C:/Windows/Fonts/georgiab.ttf" if bold else "C:/Windows/Fonts/georgia.ttf",
        ]
    elif bold:
        candidates = [
            "C:/Windows/Fonts/arialbd.ttf",
            "C:/Windows/Fonts/seguisb.ttf",
            "C:/Windows/Fonts/msyhbd.ttc",
        ]
    else:
        candidates = [
            "C:/Windows/Fonts/arial.ttf",
            "C:/Windows/Fonts/segoeui.ttf",
            "C:/Windows/Fonts/msyh.ttc",
        ]
    for candidate in candidates:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default(size=size)


F_TITLE = pick_font(34, True, serif=True)
F_SECTION = pick_font(28, True, serif=True)
F_PANEL = pick_font(20, True)
F_BODY = pick_font(17)
F_SMALL = pick_font(14)
F_CODE = pick_font(14, mono=True)
F_CODE_BOLD = pick_font(14, bold=True, mono=True)
F_TAG = pick_font(13, True)


def text(draw, x, y, s, font=F_BODY, fill=None, anchor=None):
    draw.text((x, y), s, font=font, fill=fill or PALETTE["ink"], anchor=anchor)


def rrect(draw, xy, radius=10, fill="#FFFFFF", outline=None, width=2):
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline or PALETTE["line"], width=width)


def line(draw, points, fill=None, width=3):
    draw.line(points, fill=fill or PALETTE["line"], width=width)


def arrow(draw, start, end, color=None, width=3, dashed=False):
    color = color or PALETTE["line"]
    x1, y1 = start
    x2, y2 = end
    if dashed:
        dx = x2 - x1
        dy = y2 - y1
        steps = max(1, int(((dx * dx + dy * dy) ** 0.5) // 22))
        for i in range(0, steps, 2):
            xa = x1 + dx * i / steps
            ya = y1 + dy * i / steps
            xb = x1 + dx * min(i + 1, steps) / steps
            yb = y1 + dy * min(i + 1, steps) / steps
            draw.line((xa, ya, xb, yb), fill=color, width=width)
    else:
        draw.line((x1, y1, x2, y2), fill=color, width=width)

    import math

    angle = math.atan2(y2 - y1, x2 - x1)
    size = 16
    p1 = (x2, y2)
    p2 = (x2 - size * math.cos(angle - 0.45), y2 - size * math.sin(angle - 0.45))
    p3 = (x2 - size * math.cos(angle + 0.45), y2 - size * math.sin(angle + 0.45))
    draw.polygon([p1, p2, p3], fill=color)


def box(draw, x, y, w, h, title, subtitle=None, fill="#FFFFFF", stroke=None, title_font=F_PANEL):
    rrect(draw, (x, y, x + w, y + h), 8, fill, stroke or PALETTE["line"], 2)
    text(draw, x + w / 2, y + 31, title, title_font, PALETTE["ink"], anchor="mm")
    if subtitle:
        text(draw, x + w / 2, y + h - 22, subtitle, F_SMALL, PALETTE["muted"], anchor="mm")


def pill(draw, x, y, w, h, label, fill, stroke):
    rrect(draw, (x, y, x + w, y + h), h // 2, fill, stroke, 1)
    text(draw, x + w / 2, y + h / 2 + 1, label, F_TAG, PALETTE["ink"], anchor="mm")


def cylinder(draw, x, y, w, h, title, lines_, fill, stroke):
    rrect(draw, (x, y, x + w, y + h), 8, fill, stroke, 2)
    draw.ellipse((x, y - 10, x + w, y + 22), fill="#FFFFFF", outline=stroke, width=2)
    draw.arc((x, y + h - 28, x + w, y + h + 4), 0, 180, fill=stroke, width=2)
    text(draw, x + w / 2, y + 42, title, F_PANEL, PALETTE["ink"], anchor="mm")
    for i, item in enumerate(lines_):
        text(draw, x + 26, y + 74 + 26 * i, item, F_SMALL, PALETTE["muted"])


def loop_arrow(draw, xy, color):
    x, y, w, h = xy
    arrow(draw, (x + 160, y), (x + w - 160, y), color, 3)
    arrow(draw, (x + w, y + 52), (x + w, y + h - 52), color, 3)
    arrow(draw, (x + w - 160, y + h), (x + 160, y + h), color, 3)
    arrow(draw, (x, y + h - 52), (x, y + 52), color, 3)


def render_png():
    img = Image.new("RGB", (W, H), PALETTE["paper"])
    draw = ImageDraw.Draw(img)

    # Outer frame and compact title.
    draw.rectangle((24, 24, W - 24, H - 24), outline="#D1D5DB", width=2)
    text(draw, W / 2, 72, "Repo Agent: Evidence-First Repository Investigation", F_TITLE, PALETTE["ink"], "mm")
    text(
        draw,
        W / 2,
        110,
        "Local repository evidence is constructed before optional model reasoning or code edits.",
        F_BODY,
        PALETTE["muted"],
        "mm",
    )

    # Section backgrounds.
    sections = [
        (62, 150, 630, 805, PALETTE["amber_soft"], "(a) Repository evidence construction"),
        (720, 150, 700, 805, PALETTE["blue_soft"], "(b) Evidence-guided localization loop"),
        (1448, 150, 490, 805, PALETTE["green_soft"], "(c) Reviewable decision surface"),
    ]
    for x, y, w, h, fill, label in sections:
        draw.rectangle((x, y, x + w, y + h), fill=fill, outline="#111827", width=2)
        text(draw, x + 24, y + 40, label, F_SECTION, PALETTE["ink"])

    # Legend.
    rrect(draw, (1960, 150, 2140, 262), 8, "#FFFFFF", "#9CA3AF", 1)
    arrow(draw, (1980, 180), (2048, 180), PALETTE["line"], 3)
    text(draw, 2062, 173, "data flow", F_SMALL, PALETTE["muted"])
    arrow(draw, (1980, 220), (2048, 220), PALETTE["violet"], 3, dashed=True)
    text(draw, 2062, 213, "optional", F_SMALL, PALETTE["muted"])

    # (a) Evidence construction.
    box(draw, 105, 235, 210, 74, "Local repo", "source tree", "#FFFFFF")
    box(draw, 105, 365, 210, 88, "Static parser", "symbols / routes / calls", "#FFFFFF")
    box(draw, 105, 515, 210, 88, "Chunker", "CodeChunk + FileFact", "#FFFFFF")
    arrow(draw, (210, 309), (210, 365), PALETTE["line"], 3)
    arrow(draw, (210, 453), (210, 515), PALETTE["line"], 3)

    box(draw, 390, 250, 220, 92, "Route graph", "routes_to / calls / imports", "#FFFDF8")
    box(draw, 390, 390, 220, 92, "Semantic projection", "query-to-code recall", "#FFFDF8")
    box(draw, 390, 530, 220, 92, "Evidence memory", "repo brief + role hints", "#FFFDF8")
    arrow(draw, (315, 405), (390, 296), PALETTE["line"], 3)
    arrow(draw, (315, 560), (390, 436), PALETTE["line"], 3)
    arrow(draw, (315, 560), (390, 576), PALETTE["line"], 3)

    cylinder(
        draw,
        210,
        700,
        340,
        126,
        "RepositoryIndex",
        ["CodeChunk", "FileFact", "GraphEdge", "RepositoryMemory"],
        "#FFFFFF",
        "#111827",
    )
    arrow(draw, (500, 622), (500, 700), PALETTE["line"], 3)
    arrow(draw, (210, 603), (320, 700), PALETTE["line"], 3)
    pill(draw, 205, 855, 350, 38, "cacheable, deterministic, model-free by default", "#FFFFFF", "#9CA3AF")

    # (b) Investigation loop.
    box(draw, 870, 232, 420, 68, "Repository question or bug-localization prompt", None, "#FFFFFF")
    arrow(draw, (1075, 300), (1075, 360), PALETTE["line"], 3)

    loop_arrow(draw, (805, 400, 530, 280), PALETTE["blue"])
    box(draw, 955, 365, 240, 76, "Plan", "intent + focus terms", "#FFFFFF")
    box(draw, 1190, 500, 230, 76, "Retrieve", "lexical / semantic / graph", "#FFFFFF")
    box(draw, 955, 660, 240, 76, "Observe", "read snippets + tool output", "#FFFFFF")
    box(draw, 720, 500, 230, 76, "Update", "rerank + refine query", "#FFFFFF")
    rrect(draw, (910, 488, 1240, 602), 18, "#FFFFFF", "#111827", 2)
    text(draw, 1075, 530, "Evidence State", F_PANEL, PALETTE["ink"], "mm")
    text(draw, 1075, 560, "hits, graph slice, trace, diagnostics", F_SMALL, PALETTE["muted"], "mm")

    arrow(draw, (550, 763), (910, 548), PALETTE["line"], 3)
    text(draw, 654, 722, "retrieval candidates", F_SMALL, PALETTE["muted"])

    rrect(draw, (786, 790, 1362, 895), 8, "#FFFFFF", "#111827", 2)
    text(draw, 816, 826, "Evidence diagnostics", F_PANEL, PALETTE["ink"])
    for i, metric in enumerate(["confidence", "coverage", "score gap", "graph support", "warnings"]):
        pill(draw, 816 + i * 106, 850, 94, 30, metric, PALETTE["gray_soft"], "#9CA3AF")

    # Tool belt strip.
    rrect(draw, (776, 318, 1360, 352), 6, "#FFFFFF", "#9CA3AF", 1)
    text(draw, 800, 340, "tool belt:", F_CODE_BOLD, PALETTE["ink"])
    text(draw, 890, 340, "repo_brief | find_relevant_code | list_directory | search_text | read_file | verify_project", F_CODE, PALETTE["muted"])

    # Optional model.
    rrect(draw, (780, 930, 1360, 986), 8, "#FFFFFF", "#6D28D9", 2)
    text(draw, 805, 964, "Optional OpenAI-compatible tool-calling loop: model chooses safe repo tools, evidence remains observable.", F_SMALL, PALETTE["violet"])
    arrow(draw, (1075, 930), (1075, 895), PALETTE["violet"], 3, dashed=True)

    # (c) Outputs and decisions.
    box(draw, 1500, 245, 380, 90, "Grounded answer", "ranked snippets + file/line references", "#FFFFFF")
    box(draw, 1500, 390, 380, 90, "HTML report", "shareable evidence trail", "#FFFFFF")
    box(draw, 1500, 535, 380, 90, "Evidence bundle", "Codex / Aider / OpenHands handoff", "#FFFFFF")
    arrow(draw, (1362, 548), (1500, 290), PALETTE["line"], 3)
    arrow(draw, (1362, 548), (1500, 435), PALETTE["line"], 3)
    arrow(draw, (1362, 548), (1500, 580), PALETTE["line"], 3)

    rrect(draw, (1500, 705, 1880, 833), 8, "#FFFFFF", "#6D28D9", 2)
    text(draw, 1525, 745, "Optional engineering path", F_PANEL, PALETTE["ink"])
    text(draw, 1525, 778, "inspect -> edit in workspace copy -> verify -> repair -> finish", F_SMALL, PALETTE["muted"])
    text(draw, 1525, 810, "reviewed apply-run copies approved diff back to source", F_SMALL, PALETTE["muted"])
    arrow(draw, (1360, 960), (1500, 770), PALETTE["violet"], 3, dashed=True)

    # Cross-cutting bottom band.
    rrect(draw, (62, 1010, 1938, 1160), 8, "#F9FAFB", "#111827", 2)
    text(draw, 90, 1047, "Cross-cutting controls", F_PANEL, PALETTE["ink"])
    controls = [
        ("Path safety", "allowed roots, safe joins, static-file validation"),
        ("Index hygiene", "generated caches, reports, logs, and runs are ignored"),
        ("Verification policy", "allow-listed command shapes; subprocess shell=False"),
        ("Run records", "tool calls, changed files, diff snapshots, verification output"),
    ]
    x = 90
    for title, body in controls:
        rrect(draw, (x, 1072, x + 420, 1164), 8, "#FFFFFF", "#D1D5DB", 1)
        text(draw, x + 20, 1105, title, F_PANEL, PALETTE["ink"])
        text(draw, x + 20, 1134, body, F_SMALL, PALETTE["muted"])
        x += 455

    img.save(PNG_OUT, quality=96)


def svg_text(x, y, value, size=16, weight=400, fill=None, anchor=None, family="Arial, Helvetica, sans-serif"):
    attrs = ""
    if anchor:
        attrs += f' text-anchor="{anchor}"'
    return (
        f'<text x="{x}" y="{y}" font-family="{family}" font-size="{size}" '
        f'font-weight="{weight}" fill="{fill or PALETTE["ink"]}"{attrs}>{escape(value)}</text>'
    )


def svg_rrect(x, y, w, h, fill="#FFFFFF", stroke=None, rx=8, width=2):
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" stroke="{stroke or PALETTE["line"]}" stroke-width="{width}"/>'


def svg_arrow(x1, y1, x2, y2, color=None, dashed=False, width=3):
    color = color or PALETTE["line"]
    dash = ' stroke-dasharray="14 10"' if dashed else ""
    return (
        f'<line x1="{x1}" y1="{y1}" x2="{x2 - 14}" y2="{y2}" stroke="{color}" stroke-width="{width}" stroke-linecap="round"{dash}/>'
        f'<path d="M{x2} {y2}L{x2 - 16} {y2 - 8}L{x2 - 16} {y2 + 8}Z" fill="{color}"/>'
    )


def render_svg():
    # The SVG mirrors the PNG composition with editable vector primitives.
    p = [
        f'<svg width="{W}" height="{H}" viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg">',
        f'<rect width="{W}" height="{H}" fill="{PALETTE["paper"]}"/>',
        f'<rect x="24" y="24" width="{W - 48}" height="{H - 48}" fill="none" stroke="#D1D5DB" stroke-width="2"/>',
        svg_text(W / 2, 78, "Repo Agent: Evidence-First Repository Investigation", 34, 700, anchor="middle", family="Times New Roman, serif"),
        svg_text(W / 2, 116, "Local repository evidence is constructed before optional model reasoning or code edits.", 17, 400, PALETTE["muted"], "middle"),
    ]

    sections = [
        (62, 150, 630, 805, PALETTE["amber_soft"], "(a) Repository evidence construction"),
        (720, 150, 700, 805, PALETTE["blue_soft"], "(b) Evidence-guided localization loop"),
        (1448, 150, 490, 805, PALETTE["green_soft"], "(c) Reviewable decision surface"),
    ]
    for x, y, w, h, fill, label in sections:
        p.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{fill}" stroke="#111827" stroke-width="2"/>')
        p.append(svg_text(x + 24, y + 40, label, 28, 700, family="Times New Roman, serif"))

    # A compact vector version of the detailed PNG.
    def add_box(x, y, w, h, title, subtitle=None, fill="#FFFFFF", stroke="#111827"):
        p.append(svg_rrect(x, y, w, h, fill, stroke, 8, 2))
        p.append(svg_text(x + w / 2, y + 34, title, 20, 700, anchor="middle"))
        if subtitle:
            p.append(svg_text(x + w / 2, y + h - 20, subtitle, 14, 400, PALETTE["muted"], "middle"))

    add_box(105, 235, 210, 74, "Local repo", "source tree")
    add_box(105, 365, 210, 88, "Static parser", "symbols / routes / calls")
    add_box(105, 515, 210, 88, "Chunker", "CodeChunk + FileFact")
    p += [svg_arrow(210, 309, 210, 365), svg_arrow(210, 453, 210, 515)]
    add_box(390, 250, 220, 92, "Route graph", "routes_to / calls / imports", "#FFFDF8")
    add_box(390, 390, 220, 92, "Semantic projection", "query-to-code recall", "#FFFDF8")
    add_box(390, 530, 220, 92, "Evidence memory", "repo brief + role hints", "#FFFDF8")
    p += [svg_arrow(315, 405, 390, 296), svg_arrow(315, 560, 390, 436), svg_arrow(315, 560, 390, 576)]
    p.append(svg_rrect(210, 700, 340, 126, "#FFFFFF", "#111827", 8, 2))
    p.append('<ellipse cx="380" cy="700" rx="170" ry="18" fill="#FFFFFF" stroke="#111827" stroke-width="2"/>')
    p.append(svg_text(380, 744, "RepositoryIndex", 20, 700, anchor="middle"))
    for i, item in enumerate(["CodeChunk", "FileFact", "GraphEdge", "RepositoryMemory"]):
        p.append(svg_text(236, 774 + i * 24, item, 14, 400, PALETTE["muted"]))
    p += [svg_arrow(500, 622, 500, 700), svg_arrow(210, 603, 320, 700)]
    p.append(svg_rrect(205, 855, 350, 38, "#FFFFFF", "#9CA3AF", 19, 1))
    p.append(svg_text(380, 879, "cacheable, deterministic, model-free by default", 13, 700, anchor="middle"))

    add_box(870, 232, 420, 68, "Repository question or bug-localization prompt")
    p.append(svg_arrow(1075, 300, 1075, 360))
    add_box(955, 365, 240, 76, "Plan", "intent + focus terms")
    add_box(1190, 500, 230, 76, "Retrieve", "lexical / semantic / graph")
    add_box(955, 660, 240, 76, "Observe", "read snippets + tool output")
    add_box(720, 500, 230, 76, "Update", "rerank + refine query")
    p += [
        svg_arrow(965, 400, 1174, 400, PALETTE["blue"]),
        svg_arrow(1335, 452, 1335, 625, PALETTE["blue"]),
        svg_arrow(1175, 680, 821, 680, PALETTE["blue"]),
        svg_arrow(805, 628, 805, 452, PALETTE["blue"]),
    ]
    p.append(svg_rrect(910, 488, 330, 114, "#FFFFFF", "#111827", 18, 2))
    p.append(svg_text(1075, 532, "Evidence State", 20, 700, anchor="middle"))
    p.append(svg_text(1075, 562, "hits, graph slice, trace, diagnostics", 14, 400, PALETTE["muted"], "middle"))
    p.append(svg_arrow(550, 763, 910, 548))
    p.append(svg_text(654, 722, "retrieval candidates", 14, 400, PALETTE["muted"]))
    p.append(svg_rrect(786, 790, 576, 105, "#FFFFFF", "#111827", 8, 2))
    p.append(svg_text(816, 826, "Evidence diagnostics", 20, 700))
    for i, metric in enumerate(["confidence", "coverage", "score gap", "graph support", "warnings"]):
        p.append(svg_rrect(816 + i * 106, 850, 94, 30, PALETTE["gray_soft"], "#9CA3AF", 15, 1))
        p.append(svg_text(863 + i * 106, 870, metric, 13, 700, anchor="middle"))
    p.append(svg_rrect(776, 318, 584, 34, "#FFFFFF", "#9CA3AF", 6, 1))
    p.append(svg_text(800, 340, "tool belt:", 14, 700, family="Consolas, monospace"))
    p.append(svg_text(890, 340, "repo_brief | find_relevant_code | list_directory | search_text | read_file | verify_project", 14, 400, PALETTE["muted"], family="Consolas, monospace"))
    p.append(svg_rrect(780, 930, 580, 56, "#FFFFFF", PALETTE["violet"], 8, 2))
    p.append(svg_text(805, 964, "Optional OpenAI-compatible tool-calling loop: model chooses safe repo tools, evidence remains observable.", 14, 400, PALETTE["violet"]))
    p.append(svg_arrow(1075, 930, 1075, 895, PALETTE["violet"], True))

    add_box(1500, 245, 380, 90, "Grounded answer", "ranked snippets + file/line references")
    add_box(1500, 390, 380, 90, "HTML report", "shareable evidence trail")
    add_box(1500, 535, 380, 90, "Evidence bundle", "Codex / Aider / OpenHands handoff")
    p += [svg_arrow(1362, 548, 1500, 290), svg_arrow(1362, 548, 1500, 435), svg_arrow(1362, 548, 1500, 580)]
    p.append(svg_rrect(1500, 705, 380, 128, "#FFFFFF", PALETTE["violet"], 8, 2))
    p.append(svg_text(1525, 745, "Optional engineering path", 20, 700))
    p.append(svg_text(1525, 778, "inspect -> edit in workspace copy -> verify -> repair -> finish", 14, 400, PALETTE["muted"]))
    p.append(svg_text(1525, 810, "reviewed apply-run copies approved diff back to source", 14, 400, PALETTE["muted"]))
    p.append(svg_arrow(1360, 960, 1500, 770, PALETTE["violet"], True))

    p.append(svg_rrect(62, 1010, 1876, 150, "#F9FAFB", "#111827", 8, 2))
    p.append(svg_text(90, 1047, "Cross-cutting controls", 20, 700))
    controls = [
        ("Path safety", "allowed roots, safe joins, static-file validation"),
        ("Index hygiene", "generated caches, reports, logs, and runs are ignored"),
        ("Verification policy", "allow-listed command shapes; subprocess shell=False"),
        ("Run records", "tool calls, changed files, diff snapshots, verification output"),
    ]
    x = 90
    for title, body in controls:
        p.append(svg_rrect(x, 1072, 420, 92, "#FFFFFF", "#D1D5DB", 8, 1))
        p.append(svg_text(x + 20, 1105, title, 20, 700))
        p.append(svg_text(x + 20, 1134, body, 14, 400, PALETTE["muted"]))
        x += 455

    p.append("</svg>")
    SVG_OUT.write_text("\n".join(p), encoding="utf-8")


if __name__ == "__main__":
    render_png()
    render_svg()
    print(PNG_OUT)
    print(SVG_OUT)
