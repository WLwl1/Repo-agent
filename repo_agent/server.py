from __future__ import annotations

import json
import mimetypes
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .runtime import RepoAgentRuntime
from .security import clamp_top_k, safe_join


def serve(project_root: Path, host: str = "127.0.0.1", port: int = 8787) -> None:
    runtime = RepoAgentRuntime(project_root)
    static_dir = _resolve_static_dir(project_root)
    reports_dir = runtime.reports_dir

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            try:
                parsed = urlparse(self.path)
                if parsed.path == "/":
                    return self._serve_file(static_dir / "index.html")
                if parsed.path.startswith("/static/"):
                    rel = parsed.path.removeprefix("/static/")
                    return self._serve_file(safe_join(static_dir, rel))
                if parsed.path.startswith("/reports/"):
                    rel = parsed.path.removeprefix("/reports/")
                    return self._serve_file(safe_join(reports_dir, rel))
                if parsed.path == "/api/health":
                    return self._json(runtime.health())
                if parsed.path == "/api/map":
                    params = parse_qs(parsed.query)
                    repo = params.get("repo", [""])[0]
                    if not repo:
                        return self._json({"error": "repo is required"}, status=HTTPStatus.BAD_REQUEST)
                    repo_index = runtime.load_index(repo)
                    runtime.audit.log("map", repo=str(repo_index.repo_root))
                    overview = repo_index.repository_overview()
                    overview["memory"] = runtime.repo_memory(repo)
                    return self._json(overview)
                if parsed.path == "/api/startup":
                    params = parse_qs(parsed.query)
                    repo = params.get("repo", [""])[0]
                    if not repo:
                        return self._json({"error": "repo is required"}, status=HTTPStatus.BAD_REQUEST)
                    return self._json(runtime.startup_hints(repo))
                if parsed.path == "/api/runs":
                    params = parse_qs(parsed.query)
                    limit = _int_value(params.get("limit", [30])[0], default=30, minimum=1, maximum=100)
                    return self._json({"runs": runtime.list_engineering_runs(limit=limit)})
                if parsed.path.startswith("/api/runs/"):
                    run_id = parsed.path.removeprefix("/api/runs/")
                    return self._json(runtime.read_engineering_run(run_id))
                return self._json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)
            except ValueError as error:
                runtime.audit.log("request_error", method="GET", path=self.path, error=str(error))
                return self._json({"error": str(error)}, status=HTTPStatus.BAD_REQUEST)
            except Exception as error:  # noqa: BLE001
                runtime.audit.log("request_failure", method="GET", path=self.path, error=type(error).__name__)
                return self._json({"error": "internal server error"}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

        def do_POST(self) -> None:  # noqa: N802
            try:
                parsed = urlparse(self.path)
                payload = self._read_json()
                if payload is None:
                    return
                if parsed.path == "/api/index":
                    repo = str(payload.get("repo", "")).strip()
                    force = bool(payload.get("force_rebuild"))
                    if not repo:
                        return self._json({"error": "repo is required"}, status=HTTPStatus.BAD_REQUEST)
                    repo_index = runtime.load_index(repo, force_rebuild=force)
                    return self._json({"stats": repo_index.stats()})
                if parsed.path == "/api/ask":
                    repo = str(payload.get("repo", "")).strip()
                    question = str(payload.get("question", "")).strip()
                    use_model = bool(payload.get("use_model"))
                    force = bool(payload.get("force_rebuild"))
                    top_k = clamp_top_k(payload.get("top_k", 6), runtime.config)
                    if not repo or not question:
                        return self._json({"error": "repo and question are required"}, status=HTTPStatus.BAD_REQUEST)
                    result, repo_index = runtime.ask(
                        repo_path=repo,
                        question=question,
                        top_k=top_k,
                        use_model=use_model,
                        force_rebuild=force,
                    )
                    return self._json(_serialize_result(result, repo_index.stats()))
                if parsed.path == "/api/report":
                    repo = str(payload.get("repo", "")).strip()
                    question = str(payload.get("question", "")).strip()
                    use_model = bool(payload.get("use_model"))
                    force = bool(payload.get("force_rebuild"))
                    top_k = clamp_top_k(payload.get("top_k", 6), runtime.config)
                    if not repo or not question:
                        return self._json({"error": "repo and question are required"}, status=HTTPStatus.BAD_REQUEST)
                    result, repo_index, report_path = runtime.generate_report(
                        repo_path=repo,
                        question=question,
                        top_k=top_k,
                        use_model=use_model,
                        force_rebuild=force,
                    )
                    data = _serialize_result(result, repo_index.stats())
                    data["report_url"] = f"/reports/{report_path.name}"
                    data["report_path"] = str(report_path)
                    return self._json(data)
                if parsed.path == "/api/engineer":
                    repo = str(payload.get("repo", "")).strip()
                    task = str(payload.get("task", "") or payload.get("question", "")).strip()
                    force = bool(payload.get("force_rebuild"))
                    execution_mode = str(payload.get("execution_mode", "local")).strip()
                    max_steps = _int_value(payload.get("max_steps"), default=6, minimum=1, maximum=20)
                    if not repo or not task:
                        return self._json({"error": "repo and task are required"}, status=HTTPStatus.BAD_REQUEST)
                    result, repo_index = runtime.engineer(
                        repo_path=repo,
                        task=task,
                        max_steps=max_steps,
                        execution_mode=execution_mode,
                        force_rebuild=force,
                    )
                    result["stats"] = repo_index.stats()
                    return self._json(result)
                if parsed.path == "/api/engineer/resume":
                    run_id = str(payload.get("run_id", "")).strip()
                    max_steps = _int_value(payload.get("max_steps"), default=6, minimum=1, maximum=20)
                    if not run_id:
                        return self._json({"error": "run_id is required"}, status=HTTPStatus.BAD_REQUEST)
                    result, repo_index = runtime.resume_engineering_run(run_id, max_steps=max_steps)
                    result["stats"] = repo_index.stats()
                    return self._json(result)
                if parsed.path == "/api/runs/apply":
                    run_id = str(payload.get("run_id", "")).strip()
                    confirm = bool(payload.get("confirm"))
                    if not run_id:
                        return self._json({"error": "run_id is required"}, status=HTTPStatus.BAD_REQUEST)
                    return self._json(runtime.apply_engineering_run(run_id, confirm=confirm))
                if parsed.path == "/api/tools":
                    repo = str(payload.get("repo", "")).strip()
                    action = str(payload.get("action", "")).strip()
                    force = bool(payload.get("force_rebuild"))
                    if not repo or not action:
                        return self._json({"error": "repo and action are required"}, status=HTTPStatus.BAD_REQUEST)
                    data, repo_index = runtime.workspace_tool(
                        repo_path=repo,
                        action=action,
                        payload=payload,
                        force_rebuild=force,
                    )
                    data["stats"] = repo_index.stats()
                    return self._json(data)
                return self._json({"error": "not found"}, status=HTTPStatus.NOT_FOUND)
            except ValueError as error:
                runtime.audit.log("request_error", method="POST", path=self.path, error=str(error))
                return self._json({"error": str(error)}, status=HTTPStatus.BAD_REQUEST)
            except Exception as error:  # noqa: BLE001
                runtime.audit.log("request_failure", method="POST", path=self.path, error=type(error).__name__)
                return self._json({"error": "internal server error"}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

        def log_message(self, fmt: str, *args) -> None:  # noqa: A003
            return

        def _serve_file(self, path: Path) -> None:
            if not path.exists() or not path.is_file():
                return self._json({"error": "file not found"}, status=HTTPStatus.NOT_FOUND)
            content_type, _ = mimetypes.guess_type(path.name)
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type or "application/octet-stream")
            self.end_headers()
            self.wfile.write(path.read_bytes())

        def _json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _read_json(self) -> dict | None:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length)
            try:
                return json.loads(raw.decode("utf-8")) if raw else {}
            except json.JSONDecodeError:
                self._json({"error": "invalid json"}, status=HTTPStatus.BAD_REQUEST)
                return None

    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"Repo Agent Studio is running at http://{host}:{port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


def _serialize_result(result, stats: dict) -> dict:
    return {
        "mode": result.mode,
        "query": result.query,
        "answer": result.answer,
        "trace": result.trace,
        "stats": stats,
        "model_name": result.model_name,
        "repo_brief": result.repo_brief,
        "hits": [
            {
                "source_label": hit.chunk.source_label,
                "relpath": hit.chunk.relpath,
                "symbol_name": hit.chunk.symbol_name,
                "symbol_kind": hit.chunk.symbol_kind,
                "start_line": hit.chunk.start_line,
                "end_line": hit.chunk.end_line,
                "score": hit.score,
                "matched_terms": hit.matched_terms,
                "reasons": hit.reasons,
                "snippet": hit.chunk.text,
            }
            for hit in result.hits
        ],
    }


def _resolve_static_dir(project_root: Path) -> Path:
    candidates = [
        project_root / "web",
        Path(sys.prefix) / "share" / "repo-agent" / "web",
        Path(sys.base_prefix) / "share" / "repo-agent" / "web",
    ]
    for candidate in candidates:
        if (candidate / "index.html").is_file():
            return candidate
    raise RuntimeError("Repo Agent web assets were not found")


def _int_value(value, *, default: int, minimum: int, maximum: int) -> int:
    try:
        numeric = int(value if value is not None else default)
    except (TypeError, ValueError):
        numeric = default
    return max(minimum, min(maximum, numeric))
