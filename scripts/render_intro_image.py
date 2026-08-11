# -*- coding: utf-8 -*-
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


OUT = Path(__file__).resolve().parents[1] / "assets" / "repo-agent-introduction.png"
W, H = 1600, 900


def pick_font(size, bold=False, mono=False):
    if mono:
        candidates = [
            "C:/Windows/Fonts/consolab.ttf" if bold else "C:/Windows/Fonts/consola.ttf",
        ]
    elif bold:
        candidates = [
            "C:/Windows/Fonts/msyhbd.ttc",
            "C:/Windows/Fonts/Dengb.ttf",
            "C:/Windows/Fonts/NotoSansSC-VF.ttf",
            "C:/Windows/Fonts/seguisb.ttf",
        ]
    else:
        candidates = [
            "C:/Windows/Fonts/msyh.ttc",
            "C:/Windows/Fonts/Deng.ttf",
            "C:/Windows/Fonts/NotoSansSC-VF.ttf",
            "C:/Windows/Fonts/segoeui.ttf",
        ]
    for candidate in candidates:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default(size=size)


img = Image.new("RGB", (W, H), "#F7F3EA")
d = ImageDraw.Draw(img)

f_brand = pick_font(22, True)
f_h1 = pick_font(52, True)
f_sub = pick_font(23)
f_card_title = pick_font(24, True)
f_card_body = pick_font(18)
f_node_title = pick_font(22, True)
f_node_body = pick_font(16)
f_mono_title = pick_font(20, True, True)
f_mono = pick_font(16, False, True)
f_bottom_title = pick_font(25, True)
f_bottom = pick_font(21)


def rounded(xy, radius, fill, outline=None, width=1):
    d.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)


def text(x, y, value, fill, font):
    d.text((x, y), value, fill=fill, font=font)


def line(points, fill, width=3):
    d.line(points, fill=fill, width=width, joint="curve")


rounded((44, 44, 1556, 856), 30, "#FFFDF8", "#DED7CB", 2)
line(
    [
        (93, 720),
        (230, 650),
        (352, 652),
        (487, 710),
        (610, 763),
        (761, 776),
        (882, 711),
        (1010, 642),
        (1132, 647),
        (1259, 704),
        (1360, 749),
        (1457, 750),
        (1510, 716),
    ],
    "#D8E8E9",
    18,
)
line(
    [
        (97, 178),
        (234, 120),
        (351, 123),
        (478, 170),
        (600, 215),
        (718, 206),
        (821, 153),
        (935, 94),
        (1076, 103),
        (1214, 167),
        (1328, 220),
        (1422, 223),
        (1503, 177),
    ],
    "#F0D3BF",
    18,
)

text(104, 108, "REPO AGENT", "#B55334", f_brand)
text(104, 178, "代码修改前的证据层", "#18232E", f_h1)
text(104, 244, "先定位、验证、解释，再交给 AI 编码工具。", "#5D6A75", f_sub)

cards = [
    (
        (104, 330, 609, 424),
        "#F8FBFD",
        "#C7DDE5",
        "#2A7886",
        "Evidence-first repository QA",
        "用真实文件、符号、路由和调用关系回答仓库问题。",
        "plus",
    ),
    (
        (104, 448, 609, 542),
        "#FFF8F0",
        "#EBC9A8",
        "#C56A3A",
        "Bug localization before edits",
        "先找入口、处理器、证据行和风险，再决定怎么改。",
        "warn",
    ),
    (
        (104, 566, 609, 660),
        "#F6FBF7",
        "#C9E1D2",
        "#4C8A5C",
        "Reviewable handoff",
        "导出报告、证据包与完整 trace。",
        "check",
    ),
]

for xy, fill, outline, icon, title, body, kind in cards:
    rounded(xy, 18, fill, outline, 2)
    cx, cy = 148, (xy[1] + xy[3]) // 2
    d.ellipse((cx - 19, cy - 19, cx + 19, cy + 19), fill=icon)
    if kind == "plus":
        line([(139, cy), (157, cy)], "#FFFFFF", 4)
        line([(148, cy - 9), (148, cy + 9)], "#FFFFFF", 4)
    elif kind == "warn":
        line([(139, cy + 5), (146, cy - 8), (153, cy + 5)], "#FFFFFF", 4)
    else:
        line([(139, cy), (145, cy + 7), (158, cy - 7)], "#FFFFFF", 4)
    text(184, xy[1] + 29, title, "#18232E", f_card_title)
    text(184, xy[1] + 62, body, "#63717F", f_card_body)

rounded((690, 152, 1462, 700), 28, "#FFFFFF", "#DED7CB", 2)
rounded((730, 198, 928, 330), 18, "#F6F8FA", "#D7DEE5", 2)
text(760, 232, "Local Repo", "#18232E", f_card_title)
text(760, 270, "source files", "#63717F", f_node_body)
text(760, 296, "routes, imports", "#63717F", f_node_body)

nodes = [
    ((1034, 172, 1254, 264), "#F8FBFD", "#C7DDE5", "Code Graph", "symbols + handlers"),
    ((1034, 302, 1254, 394), "#FFF8F0", "#EBC9A8", "Evidence Rank", "lexical + semantic"),
    ((1034, 432, 1254, 524), "#FAF7FF", "#D8CDED", "Diagnostics", "confidence + risk"),
]
for xy, fill, outline, title, body in nodes:
    rounded(xy, 18, fill, outline, 2)
    text(xy[0] + 30, xy[1] + 33, title, "#18232E", f_node_title)
    text(xy[0] + 30, xy[1] + 61, body, "#63717F", f_node_body)

rounded((1300, 198, 1422, 524), 18, "#F6FBF7", "#C9E1D2", 2)
text(1326, 235, "Output", "#18232E", f_node_title)
for i, item in enumerate(["Answer", "Trace", "Report", "Bundle", "Handoff"]):
    text(1326, 279 + i * 40, item, "#63717F", f_node_body)

line([(928, 264), (1010, 264)], "#9AA8B4", 3)
line([(998, 254), (1012, 264), (998, 274)], "#9AA8B4", 3)
line([(928, 264), (966, 322), (984, 420), (1010, 478)], "#9AA8B4", 3)
line([(999, 466), (1012, 480), (994, 486)], "#9AA8B4", 3)
for y in [218, 348, 478]:
    line([(1254, y), (1278, y)], "#9AA8B4", 3)
    line([(1266, y - 10), (1280, y), (1266, y + 10)], "#9AA8B4", 3)

rounded((730, 376, 928, 526), 18, "#18232E")
text(758, 409, "repo-agent ask", "#E6EDF3", f_mono_title)
for i, item in enumerate(["find route", "read files", "verify"]):
    text(758, 449 + i * 28, item, "#B9C5D0", f_mono)

rounded((730, 574, 1422, 648), 18, "#F4F0E8", "#DED7CB", 2)
text(760, 590, "Works without an API key", "#18232E", f_node_title)
text(760, 626, "deterministic retrieval first, model loop optional", "#63717F", pick_font(15))

rounded((104, 718, 1462, 802), 22, "#18232E")
text(144, 745, "CLI + Web Studio + Evidence Bundle", "#FFFFFF", f_bottom_title)
text(640, 748, "for onboarding, debugging, code review, and safer AI-assisted edits", "#B9C5D0", f_bottom)

img.save(OUT, quality=95)
print(OUT)
