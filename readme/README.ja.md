# Repo Agent

言語:

- en [English](../README.md)
- zh_CN [简体中文](README.zh_CN.md)
- ja [日本語](README.ja.md)

AI がコードを編集する前に、証拠を優先してリポジトリ調査とバグ位置特定を行うローカルツールです。

## Repo Agent とは

多くの coding agent はファイル変更を最適化します。しかし実際に編集する前に、まず答えるべき問いがあります。

> どこを見るべきか？その根拠は何か？

Repo Agent はローカルのコードベース調査ツールです。モデルに編集を依頼する前に、バグ、機能、ルート、ハンドラ、実行経路の位置を証拠付きで示すことに焦点を当てています。

- 実際のソースコードをシンボルとコードチャンクに解析
- ルート、ハンドラ、デコレータ、import、call から軽量なリポジトリグラフを構築
- lexical recall、semantic projection、graph expansion で根拠を検索
- ディレクトリ一覧、テキスト検索、ファイル読み取り、安全な検証コマンドでワークスペースを調査
- ranked evidence、行番号、trace とともに質問やバグ調査に回答
- confidence、coverage、score gap、graph support、strengths、warnings を含む evidence diagnostics を出力
- デバッグ、オンボーディング、レビュー用の HTML レポートを生成
- Codex、Aider、OpenHands などへ渡せる Markdown/JSON evidence bundle を生成
- 設定済みモデルがある場合は OpenAI 互換の tool-calling loop を利用可能

Repo Agent は完全な IDE coding agent のクローンではありません。強みはコード変更の一歩手前にあります。低コストでローカルに、説明可能でレビューしやすい証拠を作ります。

## Trust Signals

- API key なしで deterministic な graph-aware retrieval を実行
- fixture repository と CI-backed ranking metrics を同梱
- indexing 時に cache、logs、reports、run workspaces などの生成物を無視
- repository access と report/static-file serving に path validation を使用
- `shell=False` と allow-listed command shape で検証コマンドを実行
- parser、indexing、cache、security、web asset を pytest でカバー

## Positioning

Repo Agent はコード変更前の evidence layer です。Aider、OpenHands、SWE-agent、Codex などと組み合わせ、まず Repo Agent で files、handlers、routes、traces、confidence signals を見つけ、その後に編集を coding agent へ渡す使い方に向いています。

より詳しい比較は [docs/comparison.md](../docs/comparison.md) を参照してください。

## Key Capabilities

- Evidence-first repository QA and bug triage
- File、symbol、line-level evidence ranking
- Retrieval quality と risk を可視化する evidence confidence diagnostics
- Express/FastAPI/Flask 形式の route と handler の関連付け
- Multi-step investigation: plan -> file scout -> code read -> graph hop -> answer
- 結果がどのように見つかったかを示す trace
- 共有可能な HTML report
- Downstream coding agent 向け Markdown/JSON evidence bundle
- API key なしで動く deterministic retrieval
- Model mode with safe tools: `repo_brief`, `find_relevant_code`, `list_directory`, `search_text`, `read_file`, `startup_hints`, `verify_project`
- Interactive local Web Studio
- Workspace sandbox mode for edits under `runs/<run_id>/workspace`
- CI metrics: Top-1, Top-3, MRR
- Path validation、input limits、index limits
- Arbitrary `python -c`、`node -e`、package install、path traversal shaped commands をブロックする verification command policy

## When To Use It

Repo Agent は次のような場面に向いています。

- 未知のリポジトリに入るとき
- 振る舞いの背後にある route、handler、execution path を見つけるとき
- エディタを開く前に bug の疑わしい場所を絞るとき
- チームメイトにレビュー可能な evidence trail を渡すとき
- モデル token を使う前に安価な deterministic search を行うとき

十分な証拠が揃ってから、編集は full coding agent に渡します。

## Demo Questions

- `Where is the chat endpoint implemented?`
- `What should I inspect first for a streaming bug?`
- `Where does the RAG upload flow enter the codebase?`
- `What is the main execution path for this service?`
- `Can you quickly verify whether this project still runs?`

## Quick Start

### Install

```powershell
cd repo-agent
python -m pip install -e ".[dev]"
```

将来的な publish 後の想定:

```powershell
pipx install repo-agent
```

### Run the built-in eval

```powershell
python -m repo_agent eval
```

### Ask from CLI

```powershell
python -m repo_agent ask --repo ".\examples\simple_agent_app" --question "Where is the chat endpoint implemented?"
```

### Launch Web Studio

```powershell
python -m repo_agent serve
```

Then open `http://127.0.0.1:8787`.

## Real AI Agent Mode

Repo Agent はデフォルトではモデルなしで動きます。

Tool-calling agent を使う場合は `.env.example` を `.env` にコピーし、次を設定します。

- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`
- `OPENAI_MODEL`

Then run:

```powershell
python -m repo_agent ask --repo ".\examples\simple_agent_app" --question "Where is the chat endpoint implemented?" --use-model
```

`--use-model` では、モデルに安全な tool belt を渡し、すべての tool call を trace に記録します。

## Experimental Engineering Mode

Repo Agent includes an experimental engineering loop for small, controlled changes after investigation. Prefer `--execution-mode workspace` so edits happen under `runs/<run_id>/workspace` first:

```powershell
python -m repo_agent engineer --repo ".\examples\simple_agent_app" --task "Add a small health endpoint" --execution-mode workspace
```

Apply a reviewed workspace run back to the source repository:

```powershell
python -m repo_agent apply-run --run-id run_YYYYMMDD_HHMMSS_xxxxxxxx --confirm
```

## CLI Commands

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

```powershell
python -m repo_agent bundle --repo ".\examples\simple_agent_app" --question "Where is the chat endpoint implemented?" --target codex
```

Bundle には repository brief、ranked evidence、snippets、graph edges、trace steps、evidence diagnostics、handoff prompt が含まれます。

## Evaluation

```text
Summary: 11/11 passed @top3
Top-1 accuracy: 81.82%
Top-3 accuracy: 100.00%
MRR: 0.894
```

Benchmark plan: [docs/benchmarking.md](../docs/benchmarking.md)

## Quality Gate

```powershell
python -m compileall repo_agent tests
node --check web/app.js
python -m repo_agent eval
python -m pytest
```

## Configuration

See [`.env.example`](../.env.example).

## Contributing

See [CONTRIBUTING.md](../CONTRIBUTING.md). Security issues: [SECURITY.md](../SECURITY.md).

## License

[MIT](../LICENSE)
