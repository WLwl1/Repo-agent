from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .ignore import relpath_has_ignored_part
from .indexer import RepositoryIndex, detect_language

INDEX_CACHE_SCHEMA_VERSION = "2"


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
        hasher.update(f"schema={INDEX_CACHE_SCHEMA_VERSION}\n".encode("utf-8"))
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
            hasher.update(f"{relpath}|{stat.st_mtime_ns}|{stat.st_size}\n".encode("utf-8"))
        return hasher.hexdigest()

    def _cache_path(self, repo_root: Path) -> Path:
        key = hashlib.sha1(str(repo_root.resolve()).encode("utf-8")).hexdigest()
        return self.cache_dir / f"{key}.json"
