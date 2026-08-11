from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from repo_agent.agent import RepoAgent
from repo_agent.cache import IndexCache
from repo_agent.indexer import build_index, expand_query_terms
from repo_agent.parsers import analyze_source


def _workspace(name: str) -> Path:
    root = Path.cwd() / "test-workspaces" / f"{name}-{uuid.uuid4().hex}"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cleanup(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_build_index_ignores_generated_directories() -> None:
    repo_root = _workspace("index-ignore")
    try:
        _write(
            repo_root / "app.py",
            """
from fastapi import FastAPI

app = FastAPI()

@app.get("/health")
def health():
    return {"ok": True}
""".strip(),
        )
        _write(
            repo_root / "runs" / "run_123" / "workspace" / "server.js",
            "app.post('/api/chat', handleChat); function handleChat(req, res) { res.send('generated'); }",
        )
        _write(repo_root / "reports" / "report.py", "def generated_report():\n    return 'ignore me'\n")

        repo_index = build_index(repo_root)
        relpaths = {fact.relpath for fact in repo_index.file_facts}

        assert "app.py" in relpaths
        assert all(not relpath.startswith(("runs/", "reports/")) for relpath in relpaths)
        assert all(not chunk.relpath.startswith(("runs/", "reports/")) for chunk in repo_index.chunks)
    finally:
        _cleanup(repo_root.parent)


def test_cache_signature_ignores_generated_directories() -> None:
    workspace = _workspace("cache-ignore")
    repo_root = workspace / "repo"
    cache_root = workspace / "cache"
    try:
        _write(repo_root / "app.py", "def answer():\n    return 42\n")

        cache = IndexCache(cache_root)
        first_signature = cache.signature_for(repo_root)

        _write(repo_root / ".cache" / "index.py", "def generated():\n    return 'noise'\n")
        _write(repo_root / "runs" / "run_123" / "workspace" / "app.py", "def generated():\n    return 'noise'\n")

        assert cache.signature_for(repo_root) == first_signature

        _write(repo_root / "app.py", "def answer():\n    return 43\n")

        assert cache.signature_for(repo_root) != first_signature
    finally:
        _cleanup(workspace)


def test_incremental_parse_cache_round_trips_structural_analysis() -> None:
    workspace = _workspace("parse-cache")
    repo_root = workspace / "repo"
    cache_root = workspace / "cache"
    try:
        source = "export const run = () => helper();\n"
        cache = IndexCache(cache_root)
        analysis = analyze_source(Path("app.ts"), source)

        cache.save_analysis(repo_root, "app.ts", source, analysis)
        restored = cache.load_analysis(repo_root, "app.ts", source)

        assert restored is not None
        assert restored.parser_backend == "tree-sitter:typescript"
        assert restored.symbols[0].name == "run"
        assert cache.load_analysis(repo_root, "app.ts", source + "// changed") is None
        assert list(cache_root.glob("*.sqlite3"))
    finally:
        _cleanup(workspace)


def test_chinese_query_terms_expand_to_code_vocabulary() -> None:
    terms = expand_query_terms("聊天接口在哪里实现？")

    assert "聊天" in terms
    assert "chat" in terms
    assert "api" in terms
    assert "route" in terms
    assert "function" in terms


def test_chinese_web_style_query_targets_stylesheet() -> None:
    repo_root = _workspace("chinese-style-query")
    try:
        _write(repo_root / "web" / "index.html", '<link rel="stylesheet" href="styles.css">\n<div class="app"></div>\n')
        _write(repo_root / "web" / "styles.css", ".app {\n  color: red;\n}\n")
        _write(repo_root / "server.py", "def api_handler():\n    return {'ok': True}\n")

        repo_index = build_index(repo_root)
        result = repo_index.investigate("页面样式在哪里？", top_k=3)

        assert result.final_hits
        assert result.final_hits[0].chunk.relpath == "web/styles.css"
        assert result.mode == "repository_qa"
    finally:
        _cleanup(repo_root.parent)


def test_chinese_bug_query_uses_bug_localization_mode() -> None:
    repo_root = _workspace("chinese-bug-query")
    try:
        _write(
            repo_root / "server.js",
            """
function handleRequest(req, res) {
  try {
    res.json({ ok: true });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
}
""".strip(),
        )

        repo_index = build_index(repo_root)
        result = repo_index.investigate("报错时应该从哪里定位？", top_k=3)

        assert result.mode == "bug_localization"
        assert result.final_hits
        assert result.final_hits[0].chunk.relpath == "server.js"
    finally:
        _cleanup(repo_root.parent)


def test_chinese_agent_answer_is_readable_utf8() -> None:
    repo_root = _workspace("chinese-answer")
    try:
        _write(
            repo_root / "server.js",
            """
const express = require('express');
const app = express();

app.post('/api/chat', handleChat);

function handleChat(req, res) {
  res.json({ ok: true });
}
""".strip(),
        )

        result = RepoAgent(build_index(repo_root)).answer("聊天接口在哪里实现？", top_k=3)

        assert "## 结论" in result.answer
        assert "## 证据" in result.answer
        assert "最相关的位置" in result.answer
        assert "server.js" in result.answer
        assert "缁" not in result.answer
        assert "鎴" not in result.answer
    finally:
        _cleanup(repo_root.parent)


def test_agent_result_includes_evidence_diagnostics() -> None:
    repo_root = _workspace("evidence-diagnostics")
    try:
        _write(
            repo_root / "server.js",
            """
const express = require('express');
const app = express();

app.post('/api/chat', handleChat);

function handleChat(req, res) {
  res.json({ ok: true });
}
""".strip(),
        )

        result = RepoAgent(build_index(repo_root)).answer("Where is the chat endpoint implemented?", top_k=3)

        assert result.diagnostics is not None
        assert result.diagnostics.evidence_count == len(result.hits)
        assert result.diagnostics.confidence > 0
        assert result.diagnostics.label in {"low", "medium", "high"}
        assert result.diagnostics.top_score == round(result.hits[0].score, 2)
        assert "chat" in result.diagnostics.matched_terms
        assert result.graph_search["iterations"] > 0
        assert result.graph_search["top_visited"]
        assert any(item["type"] == "graph_mcts" for item in result.trace)
        assert result.proof["strategy"] == "proof_carrying_retrieval"
        assert result.proof["checks"]
    finally:
        _cleanup(repo_root.parent)


def test_mcts_graph_search_follows_call_chain_to_deep_response_writer() -> None:
    repo_root = _workspace("mcts-graph-search")
    try:
        _write(
            repo_root / "server.js",
            """
const express = require('express');
const app = express();

app.post('/api/chat', handleChat);

function handleChat(req, res) {
  return openStream(req, res);
}

function openStream(req, res) {
  const session = createSession(req.body.messages);
  return writeDelta(res, session);
}

function createSession(messages) {
  return { messages };
}

function writeDelta(res, session) {
  res.write('data: token\\n\\n');
  res.end();
}
""".strip(),
        )
        _write(
            repo_root / "docs.js",
            """
function chatOutputNotes() {
  return 'chat endpoint output documentation only';
}
""".strip(),
        )

        repo_index = build_index(repo_root)
        hits, diagnostics = repo_index.mcts_graph_search(
            "For the /api/chat endpoint, which function finally writes the response?",
            top_k=4,
            iterations=80,
            max_depth=3,
        )

        labels = [hit.chunk.source_label for hit in hits]
        visited_labels = {item["chunk"] for item in diagnostics["top_visited"]}

        assert "server.js:writeDelta" in labels
        assert "server.js:writeDelta" in visited_labels
        assert diagnostics["visited_count"] >= 4
        assert diagnostics["iterations"] == 80
    finally:
        _cleanup(repo_root.parent)


def test_apply_run_api_query_prefers_apply_action_over_run_list_renderer() -> None:
    repo_root = _workspace("apply-run-action")
    try:
        _write(
            repo_root / "web" / "app.js",
            """
function renderRuns() {
  return state.runs.map((run) => `<button data-run-action="apply">${run.id}</button>`);
}

async function refreshRuns() {
  const data = await getJSON('/api/runs?limit=20');
  state.runs = data.runs;
  renderRuns();
}

async function applyRun(runId) {
  const data = await postJSON('/api/runs/apply', { run_id: runId, confirm: true });
  await refreshRuns();
  return data;
}

async function runEngineering() {
  return postJSON('/api/engineer', {});
}
""".strip(),
        )

        repo_index = build_index(repo_root)
        result = repo_index.investigate(
            "Which Web Studio function posts to /api/runs/apply when applying a workspace run?",
            top_k=4,
        )
        labels = [hit.chunk.source_label for hit in result.final_hits]

        assert labels[0] == "web/app.js:applyRun"
        assert labels.index("web/app.js:applyRun") < labels.index("web/app.js:renderRuns")
        assert "apply-run action target" in result.final_hits[0].reasons
    finally:
        _cleanup(repo_root.parent)


def test_apply_run_query_targets_posting_action_over_render_helpers() -> None:
    repo_root = _workspace("apply-run-query")
    try:
        _write(
            repo_root / "web" / "app.js",
            """
function renderRuns(runs) {
  return runs.map((run) => `<button data-run="${run.id}">Apply</button>`).join('');
}

async function refreshRuns() {
  const response = await fetch('/api/runs');
  return response.json();
}

async function runEngineering() {
  return fetch('/api/engineering', { method: 'POST' });
}

async function applyRun(runId) {
  const response = await fetch('/api/runs/apply', {
    method: 'POST',
    body: JSON.stringify({ runId }),
  });
  await refreshRuns();
  return response.json();
}
""".strip(),
        )

        repo_index = build_index(repo_root)
        result = repo_index.investigate(
            "Which Web Studio function posts to /api/runs/apply when applying a workspace run?",
            top_k=4,
        )

        assert result.final_hits
        assert result.final_hits[0].chunk.source_label == "web/app.js:applyRun"
        assert "apply-run action target" in result.final_hits[0].reasons
        assert result.final_hits[0].score > result.final_hits[1].score
    finally:
        _cleanup(repo_root.parent)


def test_package_data_query_targets_pyproject_over_manifest_distractors() -> None:
    repo_root = _workspace("package-config-query")
    try:
        _write(
            repo_root / "pyproject.toml",
            """
[tool.setuptools.package-data]
repo_agent = ["benchmark_adapter_suite.json", "benchmark_challenge_suite.json"]
""".strip(),
        )
        _write(repo_root / "MANIFEST.in", "include repo_agent/benchmark_adapter_suite.json\n")
        _write(repo_root / "README.md", "The benchmark_adapter_suite.json file ships with the package.\n")
        _write(repo_root / "web" / "app.js", "function renderBenchmarkSuite() { return 'benchmark_adapter_suite.json'; }\n")

        repo_index = build_index(repo_root)
        result = repo_index.investigate(
            "Where is package data configured so benchmark_adapter_suite.json ships with the Python package?",
            top_k=4,
        )

        assert result.final_hits
        assert result.final_hits[0].chunk.relpath == "pyproject.toml"
        assert "package data config target" in result.final_hits[0].reasons
    finally:
        _cleanup(repo_root.parent)


def test_rag_action_queries_prefer_specific_functions_over_store_factory() -> None:
    repo_root = _workspace("rag-action-query")
    try:
        _write(
            repo_root / "server.js",
            """
const { createRagStore } = require('./lib/rag-store');
const ragStore = createRagStore();

async function runAgent(message) {
  const context = ragStore.retrieve(message, 4);
  return { message, context };
}

function handleRagText(req, res) {
  ragStore.ingestDocument([{ text: req.body?.text || '' }]);
  res.json({ ok: true, action: 'text' });
}
""".strip(),
        )
        _write(
            repo_root / "lib" / "rag-store.js",
            """
function createRagStore() {
  const documents = [];

  return { retrieve, ingestDocument, reset };

  function retrieve(query, topK) {
    return { query, topK, hits: documents.slice(0, topK) };
  }

  function ingestDocument(items) {
    documents.push(...items);
    return { ok: true };
  }

  function reset() {
    documents.length = 0;
  }
}

module.exports = { createRagStore };
""".strip(),
        )

        repo_index = build_index(repo_root)
        expected = {
            "Which handler ingests raw text into the RAG store?": "server.js:handleRagText",
            "Which server function calls the RAG store retrieval before returning agent context?": "server.js:runAgent",
            "Which library function appends uploaded or text documents into the RAG store?": "lib/rag-store.js:ingestDocument",
            "Which library function clears all documents from the RAG store?": "lib/rag-store.js:reset",
        }

        for question, expected_label in expected.items():
            result = repo_index.investigate(question, top_k=4)

            assert result.final_hits
            assert result.final_hits[0].chunk.source_label == expected_label
            assert result.final_hits[0].chunk.source_label != "lib/rag-store.js:createRagStore"
    finally:
        _cleanup(repo_root.parent)


def test_action_queries_prefer_helpers_over_route_handlers() -> None:
    repo_root = _workspace("action-helper-query")
    try:
        _write(
            repo_root / "server.js",
            """
app.post('/api/chat', handlePublicChat);
app.post('/api/admin/chat/replay', handleAdminChatReplay);
app.post('/api/chat/legacy', handleLegacyChat);

function handlePublicChat(req, res) {
  const turn = normalizePublicChatTurn(req.body.messages);
  return streamPublicChatTurn(res, turn);
}

function normalizePublicChatTurn(messages) {
  return { messages: Array.isArray(messages) ? messages : [] };
}

function streamPublicChatTurn(res, turn) {
  return writeChatDelta(res, turn);
}

function handleAdminChatReplay(req, res) {
  return writeAdminChatDelta(res, buildAdminReplay(req.body.transcript));
}

function writeAdminChatDelta(res, replay) {
  res.write(`data: ${JSON.stringify(replay)}\\n\\n`);
  res.end();
}

function buildAdminReplay(transcript) {
  return { event: 'admin.chat.replay', payload: { transcript } };
}

function handleLegacyChat(req, res) {
  return writeLegacyChatDelta(res, createLegacyChatFrame(req.body.prompt));
}

function createLegacyChatFrame(prompt) {
  return { event: 'legacy.chat.delta', payload: { prompt } };
}

function writeLegacyChatDelta(res, legacy) {
  res.write(`data: ${JSON.stringify(legacy)}\\n\\n`);
  res.end();
}
""".strip(),
        )

        repo_index = build_index(repo_root)
        expected = {
            "Which function normalizes public chat messages before streaming the /api/chat turn?": "server.js:normalizePublicChatTurn",
            "For the admin replay route, which function writes the admin-only chat replay stream?": "server.js:writeAdminChatDelta",
            "Which function builds the legacy chat frame for /api/chat/legacy?": "server.js:createLegacyChatFrame",
        }

        for question, expected_label in expected.items():
            result = repo_index.investigate(question, top_k=4)

            assert result.final_hits
            assert result.final_hits[0].chunk.source_label == expected_label
            assert not result.final_hits[0].chunk.symbol_name.startswith("handle")
    finally:
        _cleanup(repo_root.parent)


def test_fastapi_call_chain_queries_prefer_worker_helpers_over_routes() -> None:
    repo_root = _workspace("fastapi-worker-query")
    try:
        _write(
            repo_root / "app.py",
            """
from fastapi import APIRouter, FastAPI

app = FastAPI()
router = APIRouter()

@app.post("/api/chat")
async def chat_endpoint(payload: dict):
    return await run_chat(payload)

@router.get("/api/session/{session_id}")
def read_session(session_id: str):
    return load_session(session_id)

async def run_chat(payload: dict):
    return {"type": "chat", "payload": payload}

def load_session(session_id: str):
    return {"session_id": session_id}

app.include_router(router)
""".strip(),
        )

        repo_index = build_index(repo_root)
        expected = {
            "Which async function runs the FastAPI chat payload after the route entrypoint delegates?": "app.py:run_chat",
            "Which function loads a session for the FastAPI /api/session/{session_id} route?": "app.py:load_session",
        }

        for question, expected_label in expected.items():
            result = repo_index.investigate(question, top_k=4)

            assert result.final_hits
            assert result.final_hits[0].chunk.source_label == expected_label
    finally:
        _cleanup(repo_root.parent)


def test_test_file_query_downranks_coordination_cli_source() -> None:
    repo_root = _workspace("coordination-test-file-query")
    try:
        _write(
            repo_root / "repo_agent" / "__main__.py",
            """
def main():
    return coordination_status_json()

def coordination_status_json():
    return {"active_claims": []}
""".strip(),
        )
        _write(
            repo_root / "tests" / "test_coordination.py",
            """
def test_coordination_status_parses_claims_and_dirty_claimed_files():
    assert True

def test_coordination_status_reports_overlapping_active_claims():
    assert True
""".strip(),
        )
        _write(
            repo_root / "tests" / "test_indexing.py",
            """
def test_test_file_query_downranks_coordination_cli_source():
    assert 'coordination CLI active claim parsing'
""".strip(),
        )

        repo_index = build_index(repo_root)
        result = repo_index.investigate(
            "Which test file verifies the machine-readable coordination CLI and active claim parsing?",
            top_k=4,
        )

        assert result.final_hits
        assert result.final_hits[0].chunk.relpath == "tests/test_coordination.py"
        assert "coordination test target" in result.final_hits[0].reasons
    finally:
        _cleanup(repo_root.parent)


def test_web_interaction_logic_query_prefers_browser_script_over_page_shell() -> None:
    repo_root = _workspace("web-interaction-logic-query")
    try:
        _write(
            repo_root / "web" / "index.html",
            """
<main id="app">
  <button id="run">Run</button>
  <script src="app.js"></script>
</main>
""".strip(),
        )
        _write(
            repo_root / "web" / "app.js",
            """
function renderMap() {
  document.querySelector('#app').dataset.rendered = 'true';
}

function handleRunClick() {
  renderMap();
}
""".strip(),
        )

        repo_index = build_index(repo_root)
        result = repo_index.investigate("Where is the Web Studio browser interaction logic implemented?", top_k=4)

        assert result.final_hits
        assert result.final_hits[0].chunk.relpath == "web/app.js"
        assert "browser interaction logic target" in result.final_hits[0].reasons
    finally:
        _cleanup(repo_root.parent)
