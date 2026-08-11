from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "docs" / "interview-core.zh-CN.md"
MASTER_MD = ROOT / "docs" / "repo-agent-postgraduate-interview-master.zh-CN.md"
MASTER_TEX = ROOT / "docs" / "repo-agent-postgraduate-interview-master.zh-CN.tex"

APPENDICES = [
    ("附录零：超级详细技术白皮书与项目拷打大全", ROOT / "docs" / "repo-agent-complete-deep-dive.zh-CN.md"),
    ("学习入口：零基础可视化教学与开源案例册", ROOT / "docs" / "interview-visual-teaching.zh-CN.md"),
    ("附录一：项目面试参考书（代码、CLI、运行时与测试）", ROOT / "docs" / "project-interview-reference.zh-CN.md"),
    ("附录二：面试答辩作战手册（高频质疑与系统设计）", ROOT / "docs" / "interview-defense-playbook.zh-CN.md"),
    ("附录三：Repo Agent 零基础课程讲义", ROOT / "docs" / "repo-agent-course-notes.zh-CN.md"),
    ("附录四：面试案例与研究定位", ROOT / "docs" / "interview-case-study.md"),
    ("附录五：检索研究协议", ROOT / "docs" / "retrieval-research-2026.md"),
    ("附录六：评测快照与实验边界", ROOT / "docs" / "retrieval-evaluation-2026.md"),
]


def build_markdown() -> str:
    parts = [CORE.read_text(encoding="utf-8")]
    parts.append(
        "\n\n# 附录使用声明\n\n"
        "> 以下附录保留项目已有的代码走读、课程讲义和工程参考材料，用于扩大准备范围。主文档中的当前实现与实验口径优先；如果旧材料仍出现 `graph_mcts` 或 MCTS-style 表述，应理解为历史 artifact 兼容名称，当前代码实现是 bounded Personalized PageRank。\n"
    )
    for title, path in APPENDICES:
        parts.append(f"\n\n# {title}\n\n")
        parts.append(path.read_text(encoding="utf-8"))
    return "".join(parts)


def tex_escape(text: str) -> str:
    placeholders: list[str] = []

    def stash(value: str) -> str:
        token = f"@@PLACEHOLDER{len(placeholders)}@@"
        placeholders.append(value)
        return token

    text = re.sub(r"\\\[(.*?)\\\]", lambda m: stash(r"\[" + m.group(1) + r"\]"), text, flags=re.S)
    text = re.sub(r"\\\((.*?)\\\)", lambda m: stash(r"\(" + m.group(1) + r"\)"), text, flags=re.S)
    text = re.sub(r"\$(.+?)\$", lambda m: stash("$" + m.group(1) + "$"), text)
    text = text.replace("\\", r"\textbackslash{}")
    replacements = {
        "&": r"\&",
        "%": r"\%",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", lambda m: rf"\href{{{m.group(2)}}}{{{m.group(1)}}}", text)
    text = re.sub(r"`([^`]+)`", lambda m: rf"\texttt{{{m.group(1).replace('_', r'\_')}}}", text)
    text = re.sub(r"\*\*([^*]+)\*\*", lambda m: r"\textbf{" + m.group(1) + "}", text)
    text = re.sub(r"\*([^*]+)\*", lambda m: r"\emph{" + m.group(1) + "}", text)
    for index, value in enumerate(placeholders):
        text = text.replace(f"@@PLACEHOLDER{index}@@", value)
    return text


def table_to_tex(lines: list[str]) -> list[str]:
    rows: list[list[str]] = []
    for line in lines:
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if all(re.fullmatch(r":?-+:?", cell) for cell in cells):
            continue
        rows.append(cells)
    if not rows:
        return []
    columns = max(len(row) for row in rows)
    width = max(0.08, min(0.92 / columns, 0.30))
    spec = "|" + "|".join(f"p{{{width:.3f}\\textwidth}}" for _ in range(columns)) + "|"
    result = [r"\begin{center}", r"\small", rf"\begin{{longtable}}{{{spec}}}", r"\toprule"]
    for row_index, row in enumerate(rows):
        row = row + [""] * (columns - len(row))
        result.append(" & ".join(tex_escape(cell) for cell in row) + r" \\")
        if row_index == 0:
            result.append(r"\midrule")
    result.extend([r"\bottomrule", r"\end{longtable}", r"\end{center}"])
    return result


def markdown_to_tex(markdown: str) -> str:
    lines = markdown.splitlines()
    output = [
        r"\documentclass[UTF8,12pt,openany]{ctexbook}",
        r"\usepackage[a4paper,margin=2.3cm,headheight=15pt]{geometry}",
        r"\usepackage{hyperref}",
        r"\usepackage{graphicx}",
        r"\usepackage{longtable,booktabs,array}",
        r"\usepackage{xcolor}",
        r"\usepackage{enumitem}",
        r"\usepackage{listings}",
        r"\hypersetup{colorlinks=true,linkcolor=blue,urlcolor=blue}",
        r"\setlist{nosep,leftmargin=2em}",
        r"\setlength{\parindent}{2em}",
        r"\setlength{\parskip}{0.35em}",
        r"\lstset{basicstyle=\ttfamily\small,breaklines=true,columns=fullflexible,frame=single}",
        r"\begin{document}",
        r"\frontmatter",
        r"\begin{titlepage}",
        r"\centering",
        r"\vspace*{3cm}",
        r"{\Huge\bfseries Repo Agent 保研面试科研答辩手册\par}",
        r"\vspace{1.5cm}",
        r"{\Large 代码智能、软件工程智能体与可信检索\par}",
        r"\vfill",
        r"{\large 个人独立开源项目\par}",
        r"{\large 版本：2026-08-10\par}",
        r"\end{titlepage}",
        r"\tableofcontents",
        r"\mainmatter",
    ]
    in_code = False
    in_display_math = False
    code_lines: list[str] = []
    in_itemize = False
    in_enumerate = False
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.strip() == "\\[":
            if in_itemize:
                output.append(r"\end{itemize}")
                in_itemize = False
            if in_enumerate:
                output.append(r"\end{enumerate}")
                in_enumerate = False
            in_display_math = True
            output.append(r"\[")
            index += 1
            continue
        image_match = re.fullmatch(r"!\[([^\]]*)\]\(([^)]+)\)", line.strip())
        if image_match:
            if in_itemize:
                output.append(r"\end{itemize}")
                in_itemize = False
            if in_enumerate:
                output.append(r"\end{enumerate}")
                in_enumerate = False
            image_path = image_match.group(2).replace(" ", r"\ ")
            output.extend([
                r"\begin{figure}[htbp]",
                r"\centering",
                rf"\includegraphics[width=0.95\textwidth]{{{image_path}}}",
                rf"\caption{{{tex_escape(image_match.group(1))}}}",
                r"\end{figure}",
            ])
            index += 1
            continue
        if in_display_math:
            if line.strip() == "\\]":
                output.append(r"\]")
                in_display_math = False
            else:
                output.append(line)
            index += 1
            continue
        if line.startswith("```"):
            if not in_code:
                if in_itemize:
                    output.append(r"\end{itemize}")
                    in_itemize = False
                if in_enumerate:
                    output.append(r"\end{enumerate}")
                    in_enumerate = False
                in_code = True
                code_lines = []
            else:
                output.append(r"\begin{lstlisting}")
                output.extend(code_lines)
                output.append(r"\end{lstlisting}")
                in_code = False
            index += 1
            continue
        if in_code:
            code_lines.append(line)
            index += 1
            continue
        if line.startswith("|"):
            table_lines = []
            while index < len(lines) and lines[index].startswith("|"):
                table_lines.append(lines[index])
                index += 1
            if in_itemize:
                output.append(r"\end{itemize}")
                in_itemize = False
            if in_enumerate:
                output.append(r"\end{enumerate}")
                in_enumerate = False
            output.extend(table_to_tex(table_lines))
            continue
        heading = re.match(r"^(#{1,6})\s+(.*)$", line)
        if heading:
            if in_itemize:
                output.append(r"\end{itemize}")
                in_itemize = False
            if in_enumerate:
                output.append(r"\end{enumerate}")
                in_enumerate = False
            level = len(heading.group(1))
            command = {1: "chapter", 2: "section", 3: "subsection", 4: "subsubsection", 5: "paragraph", 6: "subparagraph"}[level]
            if level == 1:
                output.append(r"\clearpage")
            output.append(rf"\{command}{{{tex_escape(heading.group(2))}}}")
            index += 1
            continue
        if re.fullmatch(r"\s*---+\s*", line):
            output.append(r"\hrule")
            index += 1
            continue
        bullet = re.match(r"^\s*[-*]\s+(.*)$", line)
        number = re.match(r"^\s*\d+\.\s+(.*)$", line)
        if bullet:
            if in_enumerate:
                output.append(r"\end{enumerate}")
                in_enumerate = False
            if not in_itemize:
                output.append(r"\begin{itemize}")
                in_itemize = True
            output.append(rf"\item {tex_escape(bullet.group(1))}")
            index += 1
            continue
        if number:
            if in_itemize:
                output.append(r"\end{itemize}")
                in_itemize = False
            if not in_enumerate:
                output.append(r"\begin{enumerate}")
                in_enumerate = True
            output.append(rf"\item {tex_escape(number.group(1))}")
            index += 1
            continue
        if line.startswith("> "):
            if in_itemize:
                output.append(r"\end{itemize}")
                in_itemize = False
            if in_enumerate:
                output.append(r"\end{enumerate}")
                in_enumerate = False
            output.extend([r"\begin{quote}", tex_escape(line[2:]), r"\end{quote}"])
            index += 1
            continue
        if in_itemize:
            output.append(r"\end{itemize}")
            in_itemize = False
        if in_enumerate:
            output.append(r"\end{enumerate}")
            in_enumerate = False
        if not line.strip():
            output.append("")
        else:
            output.append(tex_escape(line) + r"\par")
        index += 1
    if in_itemize:
        output.append(r"\end{itemize}")
    if in_enumerate:
        output.append(r"\end{enumerate}")
    output.extend([r"\backmatter", r"\end{document}"])
    return "\n".join(output) + "\n"


def main() -> None:
    master = build_markdown()
    MASTER_MD.write_text(master, encoding="utf-8")
    MASTER_TEX.write_text(markdown_to_tex(master), encoding="utf-8")
    print(f"wrote {MASTER_MD} ({len(master):,} chars)")
    print(f"wrote {MASTER_TEX} ({MASTER_TEX.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
