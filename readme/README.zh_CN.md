# Repo Agent

在 AI 修改代码之前，先做证据优先的仓库调查与缺陷定位。

# README.md

- en [English](../README.md)
- zh_CN [简体中文](README.zh_CN.md)
- ja [日本語](README.ja.md)

## 为什么需要 Repo Agent

多数编码 Agent 的目标是尽快改文件。但在真正动手之前，最值得先回答的问题通常是：

> 应该先看哪里？证据是什么？

Repo Agent 是一个本地代码仓库调查工具。它的重点不是替你盲目改代码，而是在调用模型或编辑文件之前，先证明 bug、功能、路由、处理函数或执行路径最可能在哪里。

- 将真实源码解析成符号和代码块
- 从路由、处理函数、装饰器、导入和调用关系构建轻量仓库图
- 结合词法召回、语义投影和图扩展检索证据
- 使用安全工具读取目录、搜索文本、读取文件，并可运行受限验证命令
- 用带行号的排名证据、trace 和结论回答仓库问题
- 为每次回答生成 evidence diagnostics：置信度、覆盖度、分数差距、图支撑、优势与风险提示
- 导出可分享 HTML 报告，用于调试、交接和评审
- 导出 Markdown/JSON evidence bundle，交给 Codex、Aider、OpenHands 或其他编码 Agent
- 在配置模型后，可运行 OpenAI 兼容的工具调用 Agent 循环

Repo Agent 不是完整 IDE 编码 Agent 的复制品。它最锋利的地方是编码前一步：低成本、本地、可解释、可审查的证据调查。

## 亮点

- 无需 API Key 即可运行确定性的图感知检索
- 自带 fixture 仓库和 CI 支持的排名指标
- 索引时忽略生成缓存、日志、报告和运行工作区
- 对仓库访问、报告和静态文件服务做路径校验
- 使用 `shell=False` 和 allow-list 命令形状运行验证命令
- 覆盖 parser、indexing、cache、security 和 web asset 的 pytest 测试

## 定位

Repo Agent 是代码修改前的证据层。它适合与 Aider、OpenHands、SWE-agent 或 Codex 配合：先用 Repo Agent 找到文件、处理函数、路由、trace 和置信信号，再把证据交给真正负责编辑的编码 Agent。

这个项目应该被评价的是定位质量、可追踪性和可审查性，而不是“多激进地自动改代码”。更完整的对比见 [docs/comparison.md](../docs/comparison.md)。

## 核心能力

- 证据优先的仓库问答和 bug triage
- 文件级、符号级、行级证据排名
- Evidence confidence diagnostics，让检索质量和风险可见
- Express/FastAPI/Flask 风格的路由与 handler 链接
- 多步调查流程：plan -> file scout -> code read -> graph hop -> answer
- 显示结果如何被找到的 trace 输出
- 可分享 HTML 调查报告
- 面向下游编码 Agent 的 Markdown/JSON evidence bundle
- 无模型可用时仍能确定性运行
- 模型模式支持安全工具：`repo_brief`、`find_relevant_code`、`list_directory`、`search_text`、`read_file`、`startup_hints`、`verify_project`
- 本地 Web Studio 交互界面
- 工作区工具面板：目录、读文件、文本搜索、启动提示和 allow-listed 验证命令
- 实验性 engineering mode：inspect -> edit -> verify -> repair -> finish
- 工作区沙箱模式：优先编辑 `runs/<run_id>/workspace`，不直接碰源仓库
- 持久化运行记录：工具调用、变更文件、验证输出和 diff snapshot
- 内置示例仓库和可复现 demo
- CI 指标：Top-1、Top-3、MRR
- 路径校验、输入限制、索引限制等安全控制
- 集中式验证命令策略，阻止任意 `python -c`、`node -e`、包安装和路径穿越命令
- 索引、问答、map、report 和请求失败审计日志

## 适用场景

当你需要做这些事时，Repo Agent 很合适：

- 快速理解陌生仓库
- 找到某个行为背后的路由、handler 或执行路径
- 在打开编辑器前定位 bug 的可疑位置
- 给同事生成可审查的证据链
- 在花模型 token 前先做便宜的本地代码检索

当证据足够并准备真正修改代码时，再交给完整编码 Agent。

## 示例问题

可以在内置 fixture 仓库上尝试：

- `Where is the chat endpoint implemented?`
- `What should I inspect first for a streaming bug?`
- `Where does the RAG upload flow enter the codebase?`
- `What is the main execution path for this service?`
- `Can you quickly verify whether this project still runs?`

## 快速开始

### 安装

```powershell
cd repo-agent
python -m pip install -e ".[dev]"
```

未来发布后的目标安装方式：

```powershell
pipx install repo-agent
```

### 运行内置评测

```powershell
python -m repo_agent eval
```

### 从 CLI 提问

```powershell
python -m repo_agent ask --repo ".\examples\simple_agent_app" --question "Where is the chat endpoint implemented?"
```

### 启动 Web Studio

```powershell
python -m repo_agent serve
```

然后打开 `http://127.0.0.1:8787`。

## AI Agent 模式

Repo Agent 默认不需要模型。

如果想启用真实工具调用 Agent，复制 `.env.example` 为 `.env` 并设置：

- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`
- `OPENAI_MODEL`

然后运行：

```powershell
python -m repo_agent ask --repo ".\examples\simple_agent_app" --question "Where is the chat endpoint implemented?" --use-model
```

启用 `--use-model` 后，Repo Agent 会给模型一个安全工具集，并在 trace 中记录每次工具调用。模型可以检索代码、搜索文本、读取文件、查看启动提示和运行 allow-listed 验证命令，再给出最终答案。

未启用模型时，会回退到确定性的图感知检索和证据排名。

## 实验性 Engineering Mode

Repo Agent 包含一个面向小范围变更的实验性工程循环：它可以先调查文件，在工作区副本中编辑，运行 allow-listed 验证命令，并保存完整运行记录。

推荐使用 `--execution-mode workspace`，让编辑先发生在 `runs/<run_id>/workspace`：

```powershell
python -m repo_agent engineer --repo ".\examples\simple_agent_app" --task "Add a small health endpoint" --execution-mode workspace
```

只有在确认任务范围并信任编辑表面后，才直接修改源仓库：

```powershell
python -m repo_agent engineer --repo ".\examples\simple_agent_app" --task "Add a small health endpoint and verify the project still compiles" --execution-mode local
```

恢复已保存运行：

```powershell
python -m repo_agent resume --run-id run_YYYYMMDD_HHMMSS_xxxxxxxx
```

将审查后的 workspace run 应用回源仓库：

```powershell
python -m repo_agent apply-run --run-id run_YYYYMMDD_HHMMSS_xxxxxxxx --confirm
```

运行工程 benchmark：

```powershell
python -m repo_agent bench --json
```

## Web Studio

Web Studio 支持仓库路径输入、AI agent 模式、autonomous engineering、workspace-sandbox 执行、运行记录、一键索引、仓库问答、启动提示、安全工作区工具、排名证据、trace 和 HTML 报告预览。

## CLI 命令

```text
repo-agent index  --repo <path> [--force-rebuild]
repo-agent ask    --repo <path> --question "<query>" [--use-model] [--top-k <n>]
repo-agent engineer --repo <path> --task "<task>" [--execution-mode local|workspace] [--max-steps <n>] [--json]
repo-agent resume --run-id <run_id> [--max-steps <n>] [--json]
repo-agent runs [--limit <n>] [--json]
repo-agent apply-run --run-id <run_id> --confirm [--json]
repo-agent bench [--cases <path>] [--max-steps <n>] [--json]
repo-agent map    --repo <path> [--force-rebuild]
repo-agent report --repo <path> --question "<query>" [--use-model]
repo-agent bundle --repo <path> --question "<query>" [--target generic|codex|aider|openhands] [--format markdown|json]
repo-agent serve  [--host 127.0.0.1] [--port 8787]
repo-agent eval   [--top-k <n>] [--json]
```

## Evidence Bundles

当你希望 Repo Agent 完成调查阶段，再把证据交给编码 Agent 修改代码时，可以使用：

```powershell
python -m repo_agent bundle --repo ".\examples\simple_agent_app" --question "Where is the chat endpoint implemented?" --target codex
```

Bundle 包含仓库 brief、排名证据、代码片段、图关系、trace、evidence diagnostics，以及面向目标 Agent 的 handoff prompt。

## 评测

Repo Agent 自带 `examples/` fixture 仓库，所以 fresh clone 后可以直接运行 `repo-agent eval`，CI 中也可复现。

```text
Summary: 11/11 passed @top3
Top-1 accuracy: 81.82%
Top-3 accuracy: 100.00%
MRR: 0.894
```

内置 eval 是 smoke suite，不代表广泛 benchmark 领先。公开 benchmark 计划见 [docs/benchmarking.md](../docs/benchmarking.md)。

## 质量门

```powershell
python -m compileall repo_agent tests
node --check web/app.js
python -m repo_agent eval
python -m pytest
```

## 配置

见 [`.env.example`](../.env.example)：可选模型设置、允许访问的仓库根目录、question 长度限制、top-k 限制和索引限制。

## 发布前

```powershell
pwsh .\scripts\clean_generated.ps1
```

仓库 metadata、topics 和 social preview 建议见：

- [docs/github-launch-checklist.md](../docs/github-launch-checklist.md)
- [docs/repository-metadata.md](../docs/repository-metadata.md)
- [docs/benchmarking.md](../docs/benchmarking.md)
- [docs/roadmap.md](../docs/roadmap.md)

## 贡献

见 [CONTRIBUTING.md](../CONTRIBUTING.md)。

安全相关问题见 [SECURITY.md](../SECURITY.md)。

## License

[MIT](../LICENSE)
