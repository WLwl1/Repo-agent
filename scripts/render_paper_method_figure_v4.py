# -*- coding: utf-8 -*-
from pathlib import Path
from xml.sax.saxutils import escape

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
PNG_OUT = ROOT / "assets" / "repo-agent-paper-method-figure-v4.png"
SVG_OUT = ROOT / "assets" / "repo-agent-paper-method-figure-v4.svg"
W, H = 2400, 1350

COL = {
    "paper": "#FFFFFF",
    "ink": "#111827",
    "muted": "#4B5563",
    "line": "#111827",
    "soft": "#F8FAFC",
    "panel": "#F9FAFB",
    "blue": "#1D4ED8",
    "blue_soft": "#EFF6FF",
    "amber": "#B45309",
    "amber_soft": "#FFF7ED",
    "green": "#047857",
    "green_soft": "#ECFDF5",
    "violet": "#6D28D9",
    "violet_soft": "#F5F3FF",
    "stroke": "#D1D5DB",
}


def font(size, bold=False, mono=False, serif=False):
    if mono:
        names = ["consolab.ttf" if bold else "consola.ttf", "courbd.ttf" if bold else "cour.ttf"]
    elif serif:
        names = ["timesbd.ttf" if bold else "times.ttf", "georgiab.ttf" if bold else "georgia.ttf"]
    elif bold:
        names = ["arialbd.ttf", "seguisb.ttf", "msyhbd.ttc"]
    else:
        names = ["arial.ttf", "segoeui.ttf", "msyh.ttc"]
    for name in names:
        path = Path("C:/Windows/Fonts") / name
        if path.exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)


FT_TITLE = font(40, True, serif=True)
FT_SUB = font(19)
FT_SECTION = font(27, True, serif=True)
FT_BOX = font(20, True)
FT_BODY = font(16)
FT_SMALL = font(14)
FT_CODE = font(14, mono=True)
FT_TAG = font(13, True)


def text(d, x, y, s, f=FT_BODY, fill=COL["ink"], anchor=None):
    d.text((x, y), s, font=f, fill=fill, anchor=anchor)


def rect(d, xy, fill="#FFFFFF", outline=COL["line"], width=2, radius=8):
    d.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)


def box(d, x, y, w, h, title, subtitle=None, fill="#FFFFFF", outline=COL["line"]):
    rect(d, (x, y, x + w, y + h), fill, outline, 2, 8)
    text(d, x + w / 2, y + 32, title, FT_BOX, COL["ink"], "mm")
    if subtitle:
        text(d, x + w / 2, y + h - 22, subtitle, FT_SMALL, COL["muted"], "mm")


def pill(d, x, y, w, h, label, fill="#FFFFFF", outline=COL["stroke"]):
    rect(d, (x, y, x + w, y + h), fill, outline, 1, h // 2)
    text(d, x + w / 2, y + h / 2 + 1, label, FT_TAG, COL["ink"], "mm")


def cylinder(d, x, y, w, h, title, items):
    rect(d, (x, y, x + w, y + h), "#FFFFFF", COL["line"], 2, 8)
    d.ellipse((x, y - 18, x + w, y + 30), fill="#FFFFFF", outline=COL["line"], width=2)
    d.arc((x, y + h - 38, x + w, y + h + 10), 0, 180, fill=COL["line"], width=2)
    text(d, x + w / 2, y + 43, title, FT_BOX, COL["ink"], "mm")
    for i, item in enumerate(items):
        text(d, x + 30, y + 76 + i * 27, item, FT_SMALL, COL["muted"])


def arrow_head(d, p1, p2, color):
    import math

    x1, y1 = p1
    x2, y2 = p2
    angle = math.atan2(y2 - y1, x2 - x1)
    size = 17
    left = (x2 - size * math.cos(angle - 0.48), y2 - size * math.sin(angle - 0.48))
    right = (x2 - size * math.cos(angle + 0.48), y2 - size * math.sin(angle + 0.48))
    d.polygon([(x2, y2), left, right], fill=color)


def poly_arrow(d, pts, color=COL["line"], width=3, dashed=False):
    if dashed:
        for a, b in zip(pts, pts[1:]):
            x1, y1 = a
            x2, y2 = b
            steps = max(1, int((((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5) // 18))
            for i in range(0, steps, 2):
                xa = x1 + (x2 - x1) * i / steps
                ya = y1 + (y2 - y1) * i / steps
                xb = x1 + (x2 - x1) * min(i + 1, steps) / steps
                yb = y1 + (y2 - y1) * min(i + 1, steps) / steps
                d.line((xa, ya, xb, yb), fill=color, width=width)
    else:
        d.line(pts, fill=color, width=width, joint="curve")
    arrow_head(d, pts[-2], pts[-1], color)


def render_png():
    img = Image.new("RGB", (W, H), COL["paper"])
    d = ImageDraw.Draw(img)

    d.rectangle((32, 32, W - 32, H - 32), outline=COL["stroke"], width=2)
    text(d, W / 2, 75, "Repo Agent: Evidence-First Repository Investigation", FT_TITLE, COL["ink"], "mm")
    text(d, W / 2, 112, "A local evidence layer is built before optional model reasoning or code editing.", FT_SUB, COL["muted"], "mm")

    panels = [
        (70, 155, 640, 820, COL["amber_soft"], "(a) Evidence construction"),
        (750, 155, 920, 820, COL["blue_soft"], "(b) Evidence-guided localization"),
        (1710, 155, 560, 820, COL["green_soft"], "(c) Decision surface"),
    ]
    for x, y, w, h, fill, label in panels:
        d.rectangle((x, y, x + w, y + h), fill=fill, outline=COL["line"], width=2)
        text(d, x + 28, y + 42, label, FT_SECTION, COL["ink"])

    # Legend.
    rect(d, (2060, 68, 2270, 146), "#FFFFFF", COL["stroke"], 1, 8)
    poly_arrow(d, [(2082, 92), (2142, 92)], COL["line"], 3)
    text(d, 2160, 84, "primary flow", FT_SMALL, COL["muted"])
    poly_arrow(d, [(2082, 124), (2142, 124)], COL["violet"], 3, True)
    text(d, 2160, 116, "optional path", FT_SMALL, COL["muted"])

    # Panel (a): evidence construction.
    box(d, 120, 245, 230, 72, "Local repo", "source tree")
    box(d, 120, 375, 230, 86, "Static parser", "symbols, routes, calls")
    box(d, 120, 515, 230, 86, "Code facts", "chunks + file summaries")
    poly_arrow(d, [(235, 317), (235, 375)])
    poly_arrow(d, [(235, 461), (235, 515)])

    box(d, 440, 285, 230, 76, "Route graph", "route -> handler edges", "#FFFFFF")
    box(d, 440, 425, 230, 76, "Semantic signals", "query-code projection", "#FFFFFF")
    box(d, 440, 565, 230, 76, "Repo memory", "roles + brief", "#FFFFFF")
    poly_arrow(d, [(350, 560), (440, 323)])
    poly_arrow(d, [(350, 560), (440, 463)])
    poly_arrow(d, [(350, 560), (440, 603)])

    cylinder(d, 170, 740, 480, 132, "RepositoryIndex", ["CodeChunk", "FileFact", "GraphEdge", "RepositoryMemory"])
    poly_arrow(d, [(235, 601), (310, 740)])
    poly_arrow(d, [(555, 641), (555, 740)])
    pill(d, 200, 902, 420, 36, "cacheable and deterministic; no API key required")

    # Panel (b): localization pipeline.
    box(d, 840, 230, 780, 68, "Repository question or bug-localization prompt")
    rect(d, (840, 325, 1620, 44 + 325), "#FFFFFF", COL["stroke"], 1, 6)
    text(d, 865, 353, "safe tool belt:", FT_CODE, COL["ink"])
    text(d, 985, 353, "repo_brief | find_relevant_code | list_directory | search_text | read_file | verify_project", FT_CODE, COL["muted"])

    steps = [
        (790, 445, 150, 88, "Plan", "intent"),
        (985, 445, 170, 88, "Retrieve", "recall"),
        (1200, 445, 170, 88, "Inspect", "read"),
        (1415, 445, 185, 88, "Rank", "diagnose"),
    ]
    for x, y, w, h, title, sub in steps:
        box(d, x, y, w, h, title, sub)
    for current, nxt in zip(steps, steps[1:]):
        x1 = current[0] + current[2]
        poly_arrow(d, [(x1, 489), (nxt[0], 489)], COL["blue"], 3)

    rect(d, (915, 630, 1510, 122 + 630), "#FFFFFF", COL["line"], 2, 10)
    text(d, 1212, 675, "Evidence State", FT_BOX, COL["ink"], "mm")
    text(d, 1212, 705, "candidate hits, graph slice, trace events, diagnostics", FT_SMALL, COL["muted"], "mm")
    for i, label in enumerate(["confidence", "coverage", "score gap", "graph support", "warnings"]):
        pill(d, 955 + i * 104, 722, 92, 30, label, COL["soft"], COL["stroke"])

    poly_arrow(d, [(1220, 298), (1220, 445)], COL["line"], 3)
    poly_arrow(d, [(650, 806), (915, 690)], COL["line"], 3)
    text(d, 690, 770, "RepositoryIndex feeds retrieval", FT_SMALL, COL["muted"])
    poly_arrow(d, [(1510, 752), (1510, 825), (790, 825), (790, 533)], COL["violet"], 3, True)
    text(d, 930, 852, "feedback refines focus terms and evidence ranking", FT_SMALL, COL["violet"])

    rect(d, (865, 900, 1585, 50 + 900), "#FFFFFF", COL["violet"], 2, 8)
    text(d, 895, 932, "Optional model loop: the model may choose safe tools, but outputs remain tied to observed evidence.", FT_SMALL, COL["violet"])

    # Panel (c): outputs.
    box(d, 1780, 255, 420, 86, "Grounded answer", "file/line references + ranked evidence")
    box(d, 1780, 410, 420, 86, "HTML report", "reviewable evidence trail")
    box(d, 1780, 565, 420, 86, "Evidence bundle", "handoff prompt + graph context")
    junction = (1740, 489)
    poly_arrow(d, [(1600, 489), junction], COL["line"], 3)
    poly_arrow(d, [junction, (1780, 298)], COL["line"], 3)
    poly_arrow(d, [junction, (1780, 453)], COL["line"], 3)
    poly_arrow(d, [junction, (1780, 608)], COL["line"], 3)

    rect(d, (1780, 760, 420 + 1780, 118 + 760), "#FFFFFF", COL["violet"], 2, 8)
    text(d, 1808, 800, "Optional engineering path", FT_BOX, COL["ink"])
    text(d, 1808, 832, "inspect -> edit workspace copy -> verify -> repair -> finish", FT_SMALL, COL["muted"])
    text(d, 1808, 862, "reviewed apply-run copies approved diff back to source", FT_SMALL, COL["muted"])
    poly_arrow(d, [(1585, 925), (1780, 820)], COL["violet"], 3, True)

    # Bottom controls.
    rect(d, (70, 1035, 2270, 200 + 1035), "#F9FAFB", COL["line"], 2, 8)
    text(d, 100, 1076, "Cross-cutting controls and artifacts", FT_BOX, COL["ink"])
    controls = [
        ("Path safety", "allowed roots; safe joins; static file validation"),
        ("Index hygiene", "generated caches, logs, reports, and runs ignored"),
        ("Verification policy", "allow-listed command shapes; subprocess shell=False"),
        ("Run records", "tool calls, changed files, diffs, verification output"),
    ]
    x = 100
    for title, body in controls:
        rect(d, (x, 1100, x + 500, 1180), "#FFFFFF", COL["stroke"], 1, 8)
        text(d, x + 24, 1134, title, FT_BOX, COL["ink"])
        text(d, x + 24, 1162, body, FT_SMALL, COL["muted"])
        x += 540

    img.save(PNG_OUT, quality=96)


def sx(v):
    return escape(str(v))


def svg_text(x, y, s, size=16, weight=400, fill=None, anchor=None, family="Arial, Helvetica, sans-serif"):
    anchor_attr = f' text-anchor="{anchor}"' if anchor else ""
    return f'<text x="{x}" y="{y}" font-family="{family}" font-size="{size}" font-weight="{weight}" fill="{fill or COL["ink"]}"{anchor_attr}>{sx(s)}</text>'


def svg_rect(x, y, w, h, fill="#FFFFFF", stroke=None, rx=8, width=2):
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" stroke="{stroke or COL["line"]}" stroke-width="{width}"/>'


def svg_arrow(points, color=None, dashed=False, width=3):
    color = color or COL["line"]
    pts = " ".join(f"{x},{y}" for x, y in points)
    dash = ' stroke-dasharray="14 10"' if dashed else ""
    x1, y1 = points[-2]
    x2, y2 = points[-1]
    import math

    angle = math.atan2(y2 - y1, x2 - x1)
    size = 17
    p2 = (x2 - size * math.cos(angle - 0.48), y2 - size * math.sin(angle - 0.48))
    p3 = (x2 - size * math.cos(angle + 0.48), y2 - size * math.sin(angle + 0.48))
    head = f'{x2},{y2} {p2[0]:.1f},{p2[1]:.1f} {p3[0]:.1f},{p3[1]:.1f}'
    return f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="{width}" stroke-linejoin="round" stroke-linecap="round"{dash}/><polygon points="{head}" fill="{color}"/>'


def render_svg():
    # The SVG mirrors the PNG at a high level and remains editable.
    p = [
        f'<svg width="{W}" height="{H}" viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg">',
        f'<rect width="{W}" height="{H}" fill="{COL["paper"]}"/>',
        f'<rect x="32" y="32" width="{W - 64}" height="{H - 64}" fill="none" stroke="{COL["stroke"]}" stroke-width="2"/>',
        svg_text(W / 2, 82, "Repo Agent: Evidence-First Repository Investigation", 40, 700, anchor="middle", family="Times New Roman, serif"),
        svg_text(W / 2, 120, "A local evidence layer is built before optional model reasoning or code editing.", 19, 400, COL["muted"], "middle"),
    ]
    panels = [
        (70, 155, 640, 820, COL["amber_soft"], "(a) Evidence construction"),
        (750, 155, 920, 820, COL["blue_soft"], "(b) Evidence-guided localization"),
        (1710, 155, 560, 820, COL["green_soft"], "(c) Decision surface"),
    ]
    for x, y, w, h, fill, label in panels:
        p.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{fill}" stroke="{COL["line"]}" stroke-width="2"/>')
        p.append(svg_text(x + 28, y + 42, label, 27, 700, family="Times New Roman, serif"))

    def add_box(x, y, w, h, title, subtitle=None, fill="#FFFFFF"):
        p.append(svg_rect(x, y, w, h, fill, COL["line"], 8, 2))
        p.append(svg_text(x + w / 2, y + 37, title, 20, 700, anchor="middle"))
        if subtitle:
            p.append(svg_text(x + w / 2, y + h - 18, subtitle, 14, 400, COL["muted"], "middle"))

    # Legend.
    p.append(svg_rect(2060, 68, 210, 78, "#FFFFFF", COL["stroke"], 8, 1))
    p.append(svg_arrow([(2082, 92), (2142, 92)]))
    p.append(svg_text(2160, 98, "primary flow", 14, 400, COL["muted"]))
    p.append(svg_arrow([(2082, 124), (2142, 124)], COL["violet"], True))
    p.append(svg_text(2160, 130, "optional path", 14, 400, COL["muted"]))

    add_box(120, 245, 230, 72, "Local repo", "source tree")
    add_box(120, 375, 230, 86, "Static parser", "symbols, routes, calls")
    add_box(120, 515, 230, 86, "Code facts", "chunks + file summaries")
    p += [svg_arrow([(235, 317), (235, 375)]), svg_arrow([(235, 461), (235, 515)])]
    add_box(440, 285, 230, 76, "Route graph", "route -> handler edges")
    add_box(440, 425, 230, 76, "Semantic signals", "query-code projection")
    add_box(440, 565, 230, 76, "Repo memory", "roles + brief")
    p += [svg_arrow([(350, 560), (440, 323)]), svg_arrow([(350, 560), (440, 463)]), svg_arrow([(350, 560), (440, 603)])]
    p.append(svg_rect(170, 740, 480, 132, "#FFFFFF", COL["line"], 8, 2))
    p.append(f'<ellipse cx="410" cy="740" rx="240" ry="24" fill="#FFFFFF" stroke="{COL["line"]}" stroke-width="2"/>')
    p.append(svg_text(410, 784, "RepositoryIndex", 20, 700, anchor="middle"))
    for i, item in enumerate(["CodeChunk", "FileFact", "GraphEdge", "RepositoryMemory"]):
        p.append(svg_text(200, 816 + i * 27, item, 14, 400, COL["muted"]))
    p += [svg_arrow([(235, 601), (310, 740)]), svg_arrow([(555, 641), (555, 740)])]
    p.append(svg_rect(200, 902, 420, 36, "#FFFFFF", COL["stroke"], 18, 1))
    p.append(svg_text(410, 925, "cacheable and deterministic; no API key required", 13, 700, anchor="middle"))

    add_box(840, 230, 780, 68, "Repository question or bug-localization prompt")
    p.append(svg_rect(840, 325, 780, 44, "#FFFFFF", COL["stroke"], 6, 1))
    p.append(svg_text(865, 353, "safe tool belt:", 14, 400, family="Consolas, monospace"))
    p.append(svg_text(985, 353, "repo_brief | find_relevant_code | list_directory | search_text | read_file | verify_project", 14, 400, COL["muted"], family="Consolas, monospace"))
    for x, w, title, sub in [(790, 150, "Plan", "intent"), (985, 170, "Retrieve", "recall"), (1200, 170, "Inspect", "read"), (1415, 185, "Rank", "diagnose")]:
        add_box(x, 445, w, 88, title, sub)
    p += [
        svg_arrow([(940, 489), (985, 489)], COL["blue"]),
        svg_arrow([(1155, 489), (1200, 489)], COL["blue"]),
        svg_arrow([(1370, 489), (1415, 489)], COL["blue"]),
        svg_arrow([(1220, 298), (1220, 445)]),
        svg_arrow([(650, 806), (915, 690)]),
        svg_arrow([(1510, 752), (1510, 825), (790, 825), (790, 533)], COL["violet"], True),
    ]
    p.append(svg_text(690, 770, "RepositoryIndex feeds retrieval", 14, 400, COL["muted"]))
    p.append(svg_rect(915, 630, 595, 122, "#FFFFFF", COL["line"], 10, 2))
    p.append(svg_text(1212, 675, "Evidence State", 20, 700, anchor="middle"))
    p.append(svg_text(1212, 705, "candidate hits, graph slice, trace events, diagnostics", 14, 400, COL["muted"], "middle"))
    for i, label in enumerate(["confidence", "coverage", "score gap", "graph support", "warnings"]):
        p.append(svg_rect(955 + i * 104, 722, 92, 30, COL["soft"], COL["stroke"], 15, 1))
        p.append(svg_text(1001 + i * 104, 742, label, 13, 700, anchor="middle"))
    p.append(svg_text(930, 852, "feedback refines focus terms and evidence ranking", 14, 400, COL["violet"]))
    p.append(svg_rect(865, 900, 720, 50, "#FFFFFF", COL["violet"], 8, 2))
    p.append(svg_text(895, 932, "Optional model loop: the model may choose safe tools, but outputs remain tied to observed evidence.", 14, 400, COL["violet"]))

    add_box(1780, 255, 420, 86, "Grounded answer", "file/line references + ranked evidence")
    add_box(1780, 410, 420, 86, "HTML report", "reviewable evidence trail")
    add_box(1780, 565, 420, 86, "Evidence bundle", "handoff prompt + graph context")
    p += [
        svg_arrow([(1600, 489), (1740, 489)]),
        svg_arrow([(1740, 489), (1780, 298)]),
        svg_arrow([(1740, 489), (1780, 453)]),
        svg_arrow([(1740, 489), (1780, 608)]),
    ]
    p.append(svg_rect(1780, 760, 420, 118, "#FFFFFF", COL["violet"], 8, 2))
    p.append(svg_text(1808, 800, "Optional engineering path", 20, 700))
    p.append(svg_text(1808, 832, "inspect -> edit workspace copy -> verify -> repair -> finish", 14, 400, COL["muted"]))
    p.append(svg_text(1808, 862, "reviewed apply-run copies approved diff back to source", 14, 400, COL["muted"]))
    p.append(svg_arrow([(1585, 925), (1780, 820)], COL["violet"], True))

    p.append(svg_rect(70, 1035, 2200, 200, "#F9FAFB", COL["line"], 8, 2))
    p.append(svg_text(100, 1076, "Cross-cutting controls and artifacts", 20, 700))
    x = 100
    for title, body in [
        ("Path safety", "allowed roots; safe joins; static file validation"),
        ("Index hygiene", "generated caches, logs, reports, and runs ignored"),
        ("Verification policy", "allow-listed command shapes; subprocess shell=False"),
        ("Run records", "tool calls, changed files, diffs, verification output"),
    ]:
        p.append(svg_rect(x, 1100, 500, 80, "#FFFFFF", COL["stroke"], 8, 1))
        p.append(svg_text(x + 24, 1134, title, 20, 700))
        p.append(svg_text(x + 24, 1162, body, 14, 400, COL["muted"]))
        x += 540

    p.append("</svg>")
    SVG_OUT.write_text("\n".join(p), encoding="utf-8")


if __name__ == "__main__":
    render_png()
    render_svg()
    print(PNG_OUT)
    print(SVG_OUT)
