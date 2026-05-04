from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import error, request

from .models import InvestigationBundle


@dataclass(slots=True)
class LLMResponse:
    message: dict[str, Any]
    raw: dict[str, Any]


@dataclass(slots=True)
class LLMClient:
    api_key: str = ""
    base_url: str = ""
    model: str = ""
    timeout_seconds: int = 40

    @property
    def available(self) -> bool:
        return bool(self.api_key and self.base_url and self.model)

    @classmethod
    def from_env(cls, env_file: str | Path | None = None) -> "LLMClient":
        file_values = _load_env_file(env_file) if env_file else {}
        return cls(
            api_key=_env_value("OPENAI_API_KEY", file_values, "").strip(),
            base_url=_env_value("OPENAI_BASE_URL", file_values, "https://api.openai.com/v1").strip(),
            model=_env_value("OPENAI_MODEL", file_values, _env_value("MODEL", file_values, "gpt-4o-mini")).strip(),
            timeout_seconds=int(_env_value("REPO_AGENT_LLM_TIMEOUT", file_values, "40")),
        )

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        temperature: float = 0.2,
    ) -> LLMResponse | None:
        if not self.available:
            return None

        payload: dict[str, Any] = {
            "model": self.model,
            "temperature": temperature,
            "messages": messages,
        }
        if tools:
            payload["tools"] = tools
        if tool_choice is not None:
            payload["tool_choice"] = tool_choice

        data = self._post_json(self._chat_completions_url(), payload)
        if not data:
            return None
        choices = data.get("choices") or []
        if not choices:
            return None
        message = choices[0].get("message") or {}
        if not isinstance(message, dict):
            return None
        return LLMResponse(message=message, raw=data)

    def synthesize(self, query: str, bundle: InvestigationBundle, baseline_answer: str) -> str:
        if not self.available:
            return ""
        system_prompt = (
            "You are Repo Agent, a codebase analysis assistant. "
            "Answer in the same language as the user. Use only the supplied evidence. "
            "Do not invent files, functions, commands, or results."
        )
        evidence = "\n".join(
            f"- {hit.chunk.source_label} | score={hit.score:.2f} | lines={hit.chunk.start_line}-{hit.chunk.end_line}\n"
            f"  reasons: {', '.join(hit.reasons[:5])}\n"
            f"  snippet:\n{_truncate(hit.chunk.text, 18)}"
            for hit in bundle.final_hits[:5]
        )
        graph = "\n".join(
            f"- {edge.source} -> {edge.target} via {edge.label} ({edge.weight:.1f})"
            for edge in bundle.graph_edges[:8]
        )
        user_prompt = (
            f"Question:\n{query}\n\n"
            f"Task mode: {bundle.mode}\n"
            f"Focus terms: {', '.join(bundle.focus_terms[:16])}\n\n"
            f"Top evidence:\n{evidence or 'none'}\n\n"
            f"Graph edges:\n{graph or 'none'}\n\n"
            f"Deterministic baseline answer:\n{baseline_answer}\n\n"
            "Produce a concise grounded answer with clear file and line references."
        )
        response = self.chat(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
        )
        return _message_content(response.message).strip() if response else ""

    def _post_json(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        body = json.dumps(payload).encode("utf-8")
        req = request.Request(endpoint, data=body, headers=headers, method="POST")
        try:
            with request.urlopen(req, timeout=self.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except (error.URLError, json.JSONDecodeError, TimeoutError, OSError):
            return None

    def _chat_completions_url(self) -> str:
        base = self.base_url.rstrip("/")
        if base.endswith("/chat/completions"):
            return base
        return f"{base}/chat/completions"


def message_text(message: dict[str, Any]) -> str:
    return _message_content(message)


def _env_value(name: str, file_values: dict[str, str], default: str) -> str:
    value = os.environ.get(name)
    if value is not None:
        return value
    return file_values.get(name, default)


def _load_env_file(env_file: str | Path | None) -> dict[str, str]:
    if env_file is None:
        return {}
    path = Path(env_file)
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if not key:
            continue
        values[key] = _clean_env_value(value)
    return values


def _clean_env_value(value: str) -> str:
    cleaned = value.strip()
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in {"'", '"'}:
        return cleaned[1:-1]
    return cleaned


def _message_content(message: dict[str, Any]) -> str:
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
        return "\n".join(parts)
    return str(content)


def _truncate(text: str, max_lines: int) -> str:
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return text
    return "\n".join(lines[:max_lines]) + "\n..."
