from __future__ import annotations

from pathlib import Path

from repo_agent.parsers import analyze_source


def test_javascript_route_links_direct_handler() -> None:
    analysis = analyze_source(
        Path("server.js"),
        """
const express = require('express');
const app = express();

app.post('/api/chat', handleChat);

function handleChat(req, res) {
  res.json({ ok: true });
}
""",
    )

    routes = [symbol for symbol in analysis.symbols if symbol.kind == "route"]

    assert routes
    assert routes[0].name == "post_api_chat"
    assert routes[0].handler_names == ["handleChat"]


def test_python_fastapi_decorator_route() -> None:
    analysis = analyze_source(
        Path("app.py"),
        """
from fastapi import FastAPI

app = FastAPI()

@app.post('/api/chat')
def chat_endpoint():
    return {'ok': True}
""",
    )

    routes = [symbol for symbol in analysis.symbols if symbol.kind == "route"]

    assert routes
    assert routes[0].name == "post_api_chat"
    assert routes[0].handler_names == ["chat_endpoint"]

