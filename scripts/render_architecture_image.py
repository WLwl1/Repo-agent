# -*- coding: utf-8 -*-
from pathlib import Path
from xml.sax.saxutils import escape

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
PNG_OUT = ROOT / "assets" / "repo-agent-architecture-clean.png"
SVG_OUT = ROOT / "assets" / "repo-agent-architecture-clean.svg"
W, H = 1920, 1080


def pick_font(size, bold=False, mono=False):
    if mono:
        candidates = ["C:/Windows/Fonts/consolab.ttf" if bold else "C:/Windows/Fonts/consola.ttf"]
    elif bold:
        candidates = [
            "C:/Windows/Fonts/msyhbd.ttc",
            "C:/Windows/Fonts/Dengb.ttf",
            "C:/Windows/Fonts/seguisb.ttf",
            "C:/Windows/Fonts/NotoSansSC-VF.ttf",
        ]
    else:
        candidates = [
            "C:/Windows/Fonts/msyh.ttc",
            "C:/Windows/Fonts/Deng.ttf",
            "C:/Windows/Fonts/segoeui.ttf",
            "C:/Windows/Fonts/NotoSansSC-VF.ttf",
        ]
    for candidate in candidates:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default(size=size)


F_TITLE = pick_font(46, True)
F_SUB = pick_font(20)
F_STAGE = pick_font(24, True)
F_STAGE_SMALL = pick_font(15, True)
F_TEXT = pick_font(17)
F_TEXT_BOLD = pick_font(18, True)
F_SMALL = pick_font(14)
F_CODE = pick_font(14, False, True)


COLORS = {
    "ink": "#17202B",
    "muted": "#5D6B7A",
    "line": "#A9B5C2",
    "panel": "#FFFFFF",
    "bg": "#F6F8FB",
    "blue": "#276EF1",
    "teal": "#16837A",
    "orange": "#D36B2C",
    "violet": "#6F52C7",
    "green": "#3D8B55",
    "slate": "#344256",
    "soft_blue": "#EEF5FF",
    "soft_teal": "#ECF8F6",
    "soft_orange": "#FFF4EC",
    "soft_violet": "#F5F1FF",
    "soft_green": "#EEF9F0",
    "soft_slate": "#F2F5F8",
}


STAGES = [
    {
        "x": 70,
        "accent": COLORS["blue"],
        "soft": COLORS["soft_blue"],
        "label": "01",
        "title": "Inputs",
        "subtitle": "CLI / Web Studio / API",
        "items": [
            ("Repository path", "allowed roots + safe path checks"),
            ("Question or task", "ask, report, map, engineer"),
            ("Optional model config", "OpenAI-compatible endpoint"),
        ],
    },
    {
        "x": 405,
        "accent": COLORS["teal"],
        "soft": COLORS["soft_teal"],
        "label": "02",
        "title": "Runtime",
        "subtitle": "RepoAgentRuntime",
        "items": [
            ("Request validation", "limits, top-k, execution mode"),
            ("Index lifecycle", "load cache or rebuild safely"),
            ("Dispatcher", "ask/report/tools/engineer"),
        ],
    },
    {
        "x": 740,
        "accent": COLORS["orange"],
        "soft": COLORS["soft_orange"],
        "label": "03",
        "title": "Index & Graph",
        "subtitle": "parsers.py + indexer.py",
        "items": [
            ("Static parsing", "symbols, routes, imports, calls"),
            ("RepositoryIndex", "chunks, FileFact, GraphEdge"),
            ("Repo memory", "role hints + project brief"),
        ],
    },
    {
        "x": 1075,
        "accent": COLORS["violet"],
        "soft": COLORS["soft_violet"],
        "label": "04",
        "title": "Investigation",
        "subtitle": "agent.py + tools.py",
        "items": [
            ("Evidence retrieval", "lexical + semantic + graph hops"),
            ("Workspace tools", "list, search, read, verify"),
            ("Trace & diagnostics", "confidence, coverage, warnings"),
        ],
    },
    {
        "x": 1410,
        "accent": COLORS["green"],
        "soft": COLORS["soft_green"],
        "label": "05",
        "title": "Outputs",
        "subtitle": "report.py + bundle.py",
        "items": [
            ("Grounded answer", "ranked evidence + line references"),
            ("HTML report", "reviewable investigation artifact"),
            ("Evidence bundle", "handoff to Codex/Aider/OpenHands"),
        ],
    },
]


BOTTOM = [
    {
        "x": 70,
        "title": "Persistent State",
        "accent": COLORS["blue"],
        "items": [".cache/<repo-signature>.json", "runs/<run_id>/run.json", "reports/*.html"],
    },
    {
        "x": 685,
        "title": "Safety Boundary",
        "accent": COLORS["orange"],
        "items": ["path traversal protection", "ignored generated dirs", "allow-listed verification commands"],
    },
    {
        "x": 1300,
        "title": "Optional Extensions",
        "accent": COLORS["violet"],
        "items": ["model tool-calling loop", "workspace sandbox engineering", "apply reviewed run back to source"],
    },
]


def draw_arrow(draw, start, end, color, width=4, dashed=False):
    x1, y1 = start
    x2, y2 = end
    if dashed:
        total = x2 - x1
        dash, gap = 14, 10
        x = x1
        while x < x2 - 18:
            draw.line((x, y1, min(x + dash, x2 - 18), y2), fill=color, width=width)
            x += dash + gap
    else:
        draw.line((x1, y1, x2 - 18, y2), fill=color, width=width)
    draw.polygon([(x2, y2), (x2 - 20, y2 - 10), (x2 - 20, y2 + 10)], fill=color)


def draw_text(draw, xy, value, font, fill):
    draw.text(xy, value, font=font, fill=fill)


def render_png():
    img = Image.new("RGB", (W, H), COLORS["bg"])
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((36, 36, W - 36, H - 36), radius=30, fill="#FFFFFF", outline="#D8E0EA", width=2)

    draw_text(draw, (70, 72), "Repo Agent 架构图", F_TITLE, COLORS["ink"])
    draw_text(
        draw,
        (70, 128),
        "Evidence-first repository investigation before code edits: build local evidence, trace decisions, then hand off safely.",
        F_SUB,
        COLORS["muted"],
    )

    draw.rounded_rectangle((1360, 72, 1710, 150), radius=14, fill="#F7FAFC", outline="#D8E0EA", width=1)
    draw_arrow(draw, (1384, 98), (1450, 98), COLORS["blue"], width=3)
    draw_text(draw, (1470, 87), "deterministic path", F_SMALL, COLORS["muted"])
    draw_arrow(draw, (1384, 126), (1450, 126), COLORS["violet"], width=3, dashed=True)
    draw_text(draw, (1470, 115), "optional model / engineering", F_SMALL, COLORS["muted"])

    stage_y, stage_w, stage_h = 190, 300, 420
    for stage in STAGES:
        x = stage["x"]
        draw.rounded_rectangle((x, stage_y, x + stage_w, stage_y + stage_h), radius=22, fill=stage["soft"], outline="#CBD5E1", width=2)
        draw.rounded_rectangle((x, stage_y, x + stage_w, stage_y + 12), radius=6, fill=stage["accent"])
        draw.ellipse((x + 22, stage_y + 34, x + 70, stage_y + 82), fill=stage["accent"])
        draw_text(draw, (x + 35, stage_y + 47), stage["label"], F_STAGE_SMALL, "#FFFFFF")
        draw_text(draw, (x + 84, stage_y + 35), stage["title"], F_STAGE, COLORS["ink"])
        draw_text(draw, (x + 84, stage_y + 68), stage["subtitle"], F_SMALL, COLORS["muted"])

        y = stage_y + 118
        for title, body in stage["items"]:
            draw.rounded_rectangle((x + 24, y, x + stage_w - 24, y + 78), radius=14, fill="#FFFFFF", outline="#D6DEE8", width=1)
            draw_text(draw, (x + 42, y + 17), title, F_TEXT_BOLD, COLORS["ink"])
            draw_text(draw, (x + 42, y + 45), body, F_SMALL, COLORS["muted"])
            y += 94

    for a, b in zip(STAGES, STAGES[1:]):
        draw_arrow(draw, (a["x"] + stage_w + 8, stage_y + 210), (b["x"] - 8, stage_y + 210), COLORS["line"], width=4)

    draw_arrow(draw, (1225, 625), (1410, 625), COLORS["violet"], width=3, dashed=True)
    draw_text(draw, (1240, 640), "optional model-assisted refinement", F_SMALL, COLORS["violet"])

    bottom_y, bottom_w, bottom_h = 680, 550, 195
    for box in BOTTOM:
        x = box["x"]
        draw.rounded_rectangle((x, bottom_y, x + bottom_w, bottom_y + bottom_h), radius=20, fill="#FFFFFF", outline="#CBD5E1", width=2)
        draw.rectangle((x + 24, bottom_y + 32, x + 32, bottom_y + 154), fill=box["accent"])
        draw_text(draw, (x + 52, bottom_y + 28), box["title"], F_STAGE, COLORS["ink"])
        for i, item in enumerate(box["items"]):
            yy = bottom_y + 78 + i * 34
            draw.ellipse((x + 54, yy + 5, x + 64, yy + 15), fill=box["accent"])
            draw_text(draw, (x + 80, yy), item, F_TEXT, COLORS["muted"])

    draw.line((70, 915, 1710, 915), fill="#D3DBE5", width=2)
    draw.rounded_rectangle((70, 945, 1710, 1006), radius=18, fill="#17202B")
    draw_text(draw, (105, 964), "Local-first + Evidence-first", F_TEXT_BOLD, "#FFFFFF")
    draw_text(
        draw,
        (360, 964),
        "deterministic retrieval works without an API key; model loops and engineering edits are optional, constrained, and traceable.",
        F_TEXT,
        "#C9D4E0",
    )

    img.save(PNG_OUT, quality=96)


def svg_rect(x, y, w, h, fill, stroke="#CBD5E1", radius=16, width=1):
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{radius}" fill="{fill}" stroke="{stroke}" stroke-width="{width}"/>'


def svg_text(x, y, value, size=16, weight=400, fill="#17202B", family="Segoe UI, Microsoft YaHei, Arial, sans-serif"):
    return (
        f'<text x="{x}" y="{y}" fill="{fill}" font-size="{size}" '
        f'font-weight="{weight}" font-family="{family}">{escape(value)}</text>'
    )


def svg_arrow(x1, y1, x2, y2, color="#A9B5C2", dashed=False):
    dash = ' stroke-dasharray="12 10"' if dashed else ""
    return (
        f'<line x1="{x1}" y1="{y1}" x2="{x2 - 18}" y2="{y2}" stroke="{color}" '
        f'stroke-width="4" stroke-linecap="round"{dash}/>'
        f'<path d="M{x2} {y2}L{x2 - 20} {y2 - 10}L{x2 - 20} {y2 + 10}Z" fill="{color}"/>'
    )


def render_svg():
    parts = [
        f'<svg width="{W}" height="{H}" viewBox="0 0 {W} {H}" fill="none" xmlns="http://www.w3.org/2000/svg">',
        svg_rect(0, 0, W, H, COLORS["bg"], COLORS["bg"], 0, 0),
        svg_rect(36, 36, W - 72, H - 72, "#FFFFFF", "#D8E0EA", 30, 2),
        svg_text(70, 122, "Repo Agent 架构图", 46, 800),
        svg_text(
            70,
            158,
            "Evidence-first repository investigation before code edits: build local evidence, trace decisions, then hand off safely.",
            20,
            400,
            COLORS["muted"],
        ),
        svg_rect(1360, 72, 350, 78, "#F7FAFC", "#D8E0EA", 14, 1),
        svg_arrow(1384, 98, 1450, 98, COLORS["blue"]),
        svg_text(1470, 103, "deterministic path", 14, 400, COLORS["muted"]),
        svg_arrow(1384, 126, 1450, 126, COLORS["violet"], dashed=True),
        svg_text(1470, 131, "optional model / engineering", 14, 400, COLORS["muted"]),
    ]

    stage_y, stage_w, stage_h = 190, 300, 420
    for stage in STAGES:
        x = stage["x"]
        parts.append(svg_rect(x, stage_y, stage_w, stage_h, stage["soft"], "#CBD5E1", 22, 2))
        parts.append(svg_rect(x, stage_y, stage_w, 12, stage["accent"], stage["accent"], 6, 0))
        parts.append(f'<circle cx="{x + 46}" cy="{stage_y + 58}" r="24" fill="{stage["accent"]}"/>')
        parts.append(svg_text(x + 34, stage_y + 64, stage["label"], 15, 700, "#FFFFFF"))
        parts.append(svg_text(x + 84, stage_y + 58, stage["title"], 24, 800))
        parts.append(svg_text(x + 84, stage_y + 88, stage["subtitle"], 14, 400, COLORS["muted"]))
        y = stage_y + 118
        for title, body in stage["items"]:
            parts.append(svg_rect(x + 24, y, stage_w - 48, 78, "#FFFFFF", "#D6DEE8", 14, 1))
            parts.append(svg_text(x + 42, y + 32, title, 18, 700))
            parts.append(svg_text(x + 42, y + 58, body, 14, 400, COLORS["muted"]))
            y += 94

    for a, b in zip(STAGES, STAGES[1:]):
        parts.append(svg_arrow(a["x"] + stage_w + 8, stage_y + 210, b["x"] - 8, stage_y + 210))

    parts.append(svg_arrow(1225, 625, 1410, 625, COLORS["violet"], dashed=True))
    parts.append(svg_text(1240, 650, "optional model-assisted refinement", 14, 400, COLORS["violet"]))

    bottom_y, bottom_w, bottom_h = 680, 550, 195
    for box in BOTTOM:
        x = box["x"]
        parts.append(svg_rect(x, bottom_y, bottom_w, bottom_h, "#FFFFFF", "#CBD5E1", 20, 2))
        parts.append(svg_rect(x + 24, bottom_y + 32, 8, 122, box["accent"], box["accent"], 0, 0))
        parts.append(svg_text(x + 52, bottom_y + 60, box["title"], 24, 800))
        for i, item in enumerate(box["items"]):
            yy = bottom_y + 88 + i * 34
            parts.append(f'<circle cx="{x + 59}" cy="{yy - 5}" r="5" fill="{box["accent"]}"/>')
            parts.append(svg_text(x + 80, yy, item, 17, 400, COLORS["muted"]))

    parts.extend(
        [
            f'<line x1="70" y1="915" x2="1710" y2="915" stroke="#D3DBE5" stroke-width="2"/>',
            svg_rect(70, 945, 1640, 61, "#17202B", "#17202B", 18, 0),
            svg_text(105, 983, "Local-first + Evidence-first", 18, 700, "#FFFFFF"),
            svg_text(
                360,
                983,
                "deterministic retrieval works without an API key; model loops and engineering edits are optional, constrained, and traceable.",
                17,
                400,
                "#C9D4E0",
            ),
            "</svg>",
        ]
    )
    SVG_OUT.write_text("\n".join(parts), encoding="utf-8")


if __name__ == "__main__":
    render_png()
    render_svg()
    print(PNG_OUT)
    print(SVG_OUT)
