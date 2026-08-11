from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from .ignore import relpath_has_ignored_part
from .indexer import RepositoryIndex, detect_language
from .models import SourceAnalysis, Symbol

INDEX_CACHE_SCHEMA_VERSION = "3"
PARSE_CACHE_SCHEMA_VERSION = "tree-sitter-v1"


class IndexCache:
    def __init__(self, cache_dir: Path):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def load(self, repo_root: Path, signature: str) -> RepositoryIndex | None:
        cache_path = self._cache_path(repo_root)
        if not cache_path.exists():
            return None
        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if payload.get("schema_version") != INDEX_CACHE_SCHEMA_VERSION:
            return None
        if payload.get("signature") != signature:
            return None
        return RepositoryIndex.from_payload(repo_root, payload.get("index", {}))

    def save(self, repo_root: Path, signature: str, repo_index: RepositoryIndex) -> None:
        cache_path = self._cache_path(repo_root)
        payload = {
            "schema_version": INDEX_CACHE_SCHEMA_VERSION,
            "repo_root": str(repo_root),
            "signature": signature,
            "index": repo_index.to_payload(),
        }
        cache_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def signature_for(self, repo_root: Path) -> str:
        hasher = hashlib.sha256()
        hasher.update(f"schema={INDEX_CACHE_SCHEMA_VERSION}\n".encode())
        for path in sorted(repo_root.rglob("*")):
            if not path.is_file():
                continue
            relpath = path.relative_to(repo_root).as_posix()
            if relpath_has_ignored_part(relpath):
                continue
            if detect_language(path) is None:
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            hasher.update(f"{relpath}|{stat.st_mtime_ns}|{stat.st_size}\n".encode())
        return hasher.hexdigest()

    def load_analysis(self, repo_root: Path, relpath: str, text: str) -> SourceAnalysis | None:
        digest = hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()
        connection: sqlite3.Connection | None = None
        try:
            connection = self._parse_connection(repo_root)
            row = connection.execute(
                "SELECT payload FROM file_analysis WHERE relpath = ? AND digest = ? AND schema_version = ?",
                (relpath, digest, PARSE_CACHE_SCHEMA_VERSION),
            ).fetchone()
        except sqlite3.Error:
            return None
        finally:
            if connection is not None:
                connection.close()
        if row is None:
            return None
        try:
            payload = json.loads(row[0])
            return _analysis_from_payload(payload)
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            return None

    def save_analysis(self, repo_root: Path, relpath: str, text: str, analysis: SourceAnalysis) -> None:
        digest = hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()
        payload = json.dumps(_analysis_to_payload(analysis), ensure_ascii=False)
        connection: sqlite3.Connection | None = None
        try:
            connection = self._parse_connection(repo_root)
            connection.execute(
                """
                INSERT INTO file_analysis(relpath, digest, schema_version, payload)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(relpath) DO UPDATE SET
                    digest = excluded.digest,
                    schema_version = excluded.schema_version,
                    payload = excluded.payload
                """,
                (relpath, digest, PARSE_CACHE_SCHEMA_VERSION, payload),
            )
            connection.commit()
        except sqlite3.Error:
            return
        finally:
            if connection is not None:
                connection.close()

    def _cache_path(self, repo_root: Path) -> Path:
        key = hashlib.sha1(str(repo_root.resolve()).encode("utf-8")).hexdigest()
        return self.cache_dir / f"{key}.json"

    def _parse_connection(self, repo_root: Path) -> sqlite3.Connection:
        key = hashlib.sha1(str(repo_root.resolve()).encode("utf-8")).hexdigest()
        connection = sqlite3.connect(self.cache_dir / f"{key}.sqlite3", timeout=10.0)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS file_analysis (
                relpath TEXT PRIMARY KEY,
                digest TEXT NOT NULL,
                schema_version TEXT NOT NULL,
                payload TEXT NOT NULL
            )
            """
        )
        return connection


def _analysis_to_payload(analysis: SourceAnalysis) -> dict:
    return {
        "language": analysis.language,
        "imports": analysis.imports,
        "parser_backend": analysis.parser_backend,
        "symbols": [
            {
                "name": symbol.name,
                "kind": symbol.kind,
                "start_line": symbol.start_line,
                "end_line": symbol.end_line,
                "calls": symbol.calls,
                "references": symbol.references,
                "inherits": symbol.inherits,
                "qualified_name": symbol.qualified_name,
                "route_path": symbol.route_path,
                "handler_names": symbol.handler_names,
            }
            for symbol in analysis.symbols
        ],
    }


def _analysis_from_payload(payload: dict) -> SourceAnalysis:
    return SourceAnalysis(
        language=str(payload["language"]),
        imports=[str(item) for item in payload.get("imports", [])],
        parser_backend=str(payload.get("parser_backend", "fallback")),
        symbols=[
            Symbol(
                name=str(item["name"]),
                kind=str(item["kind"]),
                start_line=int(item["start_line"]),
                end_line=int(item["end_line"]),
                calls=[str(value) for value in item.get("calls", [])],
                references=[str(value) for value in item.get("references", [])],
                inherits=[str(value) for value in item.get("inherits", [])],
                qualified_name=str(item.get("qualified_name", "")),
                route_path=str(item.get("route_path", "")),
                handler_names=[str(value) for value in item.get("handler_names", [])],
            )
            for item in payload.get("symbols", [])
        ],
    )
