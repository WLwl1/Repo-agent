from __future__ import annotations

import ast
import re
from pathlib import Path

from .models import SourceAnalysis, Symbol

SUPPORTED_EXTENSIONS = {
    ".py": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".jsx": "javascript",
    ".html": "html",
    ".css": "css",
}

FUNCTION_RE = re.compile(
    r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_][A-Za-z0-9_]*)|"
    r"^\s*(?:export\s+)?class\s+([A-Za-z_][A-Za-z0-9_]*)|"
    r"^\s*(?:export\s+)?const\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?:async\s*)?\(",
    re.MULTILINE,
)
IMPORT_RE = re.compile(
    r"""(?:import\s+.+?\s+from\s+['"]([^'"]+)['"])|(?:require\(\s*['"]([^'"]+)['"]\s*\))"""
)
ROUTE_OWNER_RE = r"(?:app|router|server|[A-Za-z_][A-Za-z0-9_]*(?:Router|Routes|Controller))"
ROUTE_RE = re.compile(
    rf"""\b{ROUTE_OWNER_RE}\.(get|post|put|patch|delete|use)\(\s*['"]([^'"]+)['"]"""
)
CHAINED_ROUTE_RE = re.compile(
    rf"""\b{ROUTE_OWNER_RE}\.route\(\s*['"]([^'"]+)['"]\s*\)\s*\.(get|post|put|patch|delete|use)\("""
)
CALL_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")
DIRECT_HANDLER_RE = re.compile(r",\s*([A-Za-z_][A-Za-z0-9_]*)\s*(?=[,);])")
HTML_IMPORT_RE = re.compile(r"""(?:src|href)=['"]([^'"]+)['"]""", re.IGNORECASE)
CSS_IMPORT_RE = re.compile(r"""@import\s+(?:url\()?['"]?([^'")]+)""", re.IGNORECASE)

JS_CALL_BLACKLIST = {
    "app",
    "router",
    "express",
    "req",
    "res",
    "next",
    "request",
    "response",
    "if",
    "for",
    "while",
    "switch",
    "catch",
    "return",
    "console",
    "get",
    "post",
    "put",
    "patch",
    "delete",
    "use",
    "settimeout",
    "setinterval",
    "array",
    "json",
    "send",
    "status",
}
PY_ROUTE_METHODS = {"route", "api_route", "get", "post", "put", "patch", "delete"}


def detect_language(path: Path) -> str | None:
    return SUPPORTED_EXTENSIONS.get(path.suffix.lower())


def analyze_source(path: Path, text: str) -> SourceAnalysis:
    language = detect_language(path)
    if language == "python":
        return _analyze_python(text)
    if language in {"javascript", "typescript"}:
        return _analyze_javascript(language, text)
    if language == "html":
        return _analyze_html(text)
    if language == "css":
        return _analyze_css(text)
    return SourceAnalysis(language=language or "unknown", imports=[], symbols=[])


def _analyze_python(text: str) -> SourceAnalysis:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return SourceAnalysis(language="python", imports=[], symbols=[])

    imports: list[str] = []
    symbols: list[Symbol] = []

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module_name = node.module or ""
            imports.append(module_name)

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for method, route_path, route_line in _extract_python_routes(node):
                symbols.append(
                    Symbol(
                        name=_route_symbol_name(method, route_path),
                        kind="route",
                        start_line=route_line,
                        end_line=node.lineno,
                        calls=[node.name],
                        route_path=route_path,
                        handler_names=[node.name],
                    )
                )
            symbols.append(
                Symbol(
                    name=node.name,
                    kind="function",
                    start_line=node.lineno,
                    end_line=getattr(node, "end_lineno", node.lineno),
                    calls=_extract_python_calls(node),
                )
            )
        elif isinstance(node, ast.ClassDef):
            symbols.append(
                Symbol(
                    name=node.name,
                    kind="class",
                    start_line=node.lineno,
                    end_line=getattr(node, "end_lineno", node.lineno),
                    calls=_extract_python_calls(node),
                )
            )

    symbols.sort(key=lambda item: (item.start_line, item.end_line, item.name))
    return SourceAnalysis(language="python", imports=_dedupe(imports), symbols=symbols)


def _analyze_javascript(language: str, text: str) -> SourceAnalysis:
    imports = [
        first or second
        for first, second in IMPORT_RE.findall(text)
        if (first or second)
    ]
    line_offsets = _line_offsets(text)
    line_count = max(1, len(text.splitlines()))
    raw_symbols: list[Symbol] = []

    for match in FUNCTION_RE.finditer(text):
        name = next((group for group in match.groups() if group), "")
        kind = "class" if "class" in match.group(0) else "function"
        raw_symbols.append(
            Symbol(
                name=name,
                kind=kind,
                start_line=_line_for_offset(line_offsets, match.start()),
                end_line=0,
            )
        )

    route_matches: list[tuple[int, str, str]] = []
    route_matches.extend((match.start(), match.group(1), match.group(2)) for match in ROUTE_RE.finditer(text))
    route_matches.extend((match.start(), match.group(2), match.group(1)) for match in CHAINED_ROUTE_RE.finditer(text))

    for start_offset, method, route in sorted(route_matches):
        start_line = _line_for_offset(line_offsets, start_offset)
        snippet = text[start_offset : min(len(text), start_offset + 320)]
        closing_index = snippet.find(");")
        if closing_index != -1:
            snippet = snippet[: closing_index + 2]
        end_line = _line_for_offset(line_offsets, start_offset + len(snippet))
        handler_names = _extract_js_route_handlers(snippet)
        raw_symbols.append(
            Symbol(
                name=_route_symbol_name(method, route),
                kind="route",
                start_line=start_line,
                end_line=end_line,
                calls=handler_names,
                route_path=route,
                handler_names=handler_names,
            )
        )

    raw_symbols.sort(key=lambda item: (item.start_line, item.name))
    symbols: list[Symbol] = []
    for index, symbol in enumerate(raw_symbols):
        next_start = raw_symbols[index + 1].start_line if index + 1 < len(raw_symbols) else line_count
        end_line = symbol.end_line or min(max(symbol.start_line + 4, next_start - 1), line_count)
        snippet = _slice_lines(text, symbol.start_line, end_line)
        calls = symbol.calls or _extract_js_calls(snippet)
        symbols.append(
            Symbol(
                name=symbol.name,
                kind=symbol.kind,
                start_line=symbol.start_line,
                end_line=end_line,
                calls=_dedupe(calls),
                route_path=symbol.route_path,
                handler_names=symbol.handler_names,
            )
        )

    deduped_symbols: list[Symbol] = []
    seen: set[tuple[str, int, str]] = set()
    for symbol in symbols:
        key = (symbol.name, symbol.start_line, symbol.kind)
        if key not in seen:
            seen.add(key)
            deduped_symbols.append(symbol)
    return SourceAnalysis(language=language, imports=_dedupe(imports), symbols=deduped_symbols)


def _analyze_html(text: str) -> SourceAnalysis:
    imports = [
        _normalize_static_import(match)
        for match in HTML_IMPORT_RE.findall(text)
        if _normalize_static_import(match)
    ]
    return SourceAnalysis(language="html", imports=_dedupe(imports), symbols=[])


def _analyze_css(text: str) -> SourceAnalysis:
    imports = [
        _normalize_static_import(match)
        for match in CSS_IMPORT_RE.findall(text)
        if _normalize_static_import(match)
    ]
    return SourceAnalysis(language="css", imports=_dedupe(imports), symbols=[])


def _extract_python_calls(node: ast.AST) -> list[str]:
    names: list[str] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            name = _python_call_name(child.func)
            if name:
                names.append(name)
    return _dedupe(names)


def _extract_python_routes(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[tuple[str, str, int]]:
    routes: list[tuple[str, str, int]] = []
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        method = _python_route_method(decorator.func)
        if not method:
            continue
        route_path = _python_route_path(decorator)
        if not route_path:
            continue
        for expanded_method in _expand_python_route_methods(method, decorator):
            routes.append((expanded_method, route_path, getattr(decorator, "lineno", node.lineno)))
    return routes


def _python_route_method(node: ast.AST) -> str:
    if isinstance(node, ast.Attribute) and node.attr in PY_ROUTE_METHODS:
        return node.attr
    if isinstance(node, ast.Name) and node.id in PY_ROUTE_METHODS:
        return node.id
    return ""


def _python_route_path(decorator: ast.Call) -> str:
    if decorator.args and isinstance(decorator.args[0], ast.Constant) and isinstance(decorator.args[0].value, str):
        return decorator.args[0].value
    for keyword in decorator.keywords:
        if keyword.arg in {"path", "rule"} and isinstance(keyword.value, ast.Constant):
            if isinstance(keyword.value.value, str):
                return keyword.value.value
    return ""


def _expand_python_route_methods(method: str, decorator: ast.Call) -> list[str]:
    if method not in {"route", "api_route"}:
        return [method]
    for keyword in decorator.keywords:
        if keyword.arg != "methods":
            continue
        values = _literal_string_list(keyword.value)
        if values:
            return [value.lower() for value in values]
    return ["route"]


def _literal_string_list(node: ast.AST) -> list[str]:
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return [
            item.value
            for item in node.elts
            if isinstance(item, ast.Constant) and isinstance(item.value, str)
        ]
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    return []


def _python_call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _extract_js_calls(snippet: str) -> list[str]:
    calls: list[str] = []
    for match in CALL_RE.finditer(snippet):
        name = match.group(1)
        if name.lower() in JS_CALL_BLACKLIST:
            continue
        calls.append(name)
    return _dedupe(calls)


def _extract_js_route_handlers(snippet: str) -> list[str]:
    direct_handlers = DIRECT_HANDLER_RE.findall(snippet)
    named_calls = [
        call
        for call in _extract_js_calls(snippet)
        if call.lower().startswith("handle") or call.lower().endswith("request")
    ]
    return _dedupe(
        [
            name
            for name in [*direct_handlers, *named_calls]
            if name.lower() not in JS_CALL_BLACKLIST
        ]
    )


def _route_symbol_name(method: str, route_path: str) -> str:
    safe_route = re.sub(r"[^A-Za-z0-9_]+", "_", route_path.strip("/")) or "root"
    return f"{method.lower()}_{safe_route.strip('_') or 'root'}"


def _normalize_static_import(value: str) -> str:
    normalized = value.strip().replace("\\", "/")
    if normalized.startswith("/static/"):
        normalized = normalized.removeprefix("/static/")
    return normalized


def _slice_lines(text: str, start_line: int, end_line: int) -> str:
    lines = text.splitlines()
    safe_start = max(start_line - 1, 0)
    safe_end = min(end_line, len(lines))
    return "\n".join(lines[safe_start:safe_end])


def _line_offsets(text: str) -> list[int]:
    offsets = [0]
    for index, char in enumerate(text):
        if char == "\n":
            offsets.append(index + 1)
    offsets.append(len(text) + 1)
    return offsets


def _line_for_offset(offsets: list[int], offset: int) -> int:
    for index, start in enumerate(offsets):
        if start > offset:
            return max(index, 1)
    return max(len(offsets) - 1, 1)


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = value.strip()
        if not normalized:
            continue
        lowered = normalized.lower()
        if lowered not in seen:
            seen.add(lowered)
            result.append(normalized)
    return result
