from __future__ import annotations

from functools import lru_cache
from typing import Any
from collections.abc import Iterable, Iterator

from .models import SourceAnalysis, Symbol


ROUTE_METHODS = {"get", "post", "put", "patch", "delete", "options", "head", "use"}
DEFINITION_TYPES = {
    "function_declaration": "function",
    "generator_function_declaration": "function",
    "class_declaration": "class",
    "method_definition": "method",
    "interface_declaration": "interface",
    "type_alias_declaration": "type",
    "enum_declaration": "enum",
}
FUNCTION_VALUE_TYPES = {"arrow_function", "function_expression", "generator_function"}
# The current Python Tree-sitter 0.26 bindings can crash the interpreter on
# some large template-heavy JavaScript files instead of raising an exception.
# Large files use the parser module's deterministic fallback until segmented
# parsing is available; a process-level failure is never an acceptable index
# outcome.
MAX_TREE_SITTER_SOURCE_BYTES = 20 * 1024


@lru_cache(maxsize=4)
def _parser(language: str) -> Any:
    from tree_sitter import Language, Parser

    if language == "javascript":
        import tree_sitter_javascript

        grammar = Language(tree_sitter_javascript.language())
    elif language == "typescript":
        import tree_sitter_typescript

        grammar = Language(tree_sitter_typescript.language_typescript())
    elif language == "tsx":
        import tree_sitter_typescript

        grammar = Language(tree_sitter_typescript.language_tsx())
    else:
        raise ValueError(f"unsupported Tree-sitter language: {language}")
    # Keep the Language Python object alive alongside Parser.  Some binding
    # builds retain only the native language pointer; allowing ``grammar`` to
    # be collected can surface later as a process-level access violation on a
    # sufficiently large syntax tree.
    return Parser(grammar), grammar


def tree_sitter_available(language: str) -> bool:
    try:
        _parser(language)
    except (ImportError, OSError, RuntimeError, ValueError):
        return False
    return True


def analyze_javascript_like(language: str, text: str) -> SourceAnalysis | None:
    if len(text.encode("utf-8", errors="replace")) > MAX_TREE_SITTER_SOURCE_BYTES:
        return None
    parser_language = (
        "tsx" if language == "typescript" and _looks_like_tsx(text) else language
    )
    try:
        parser, _grammar = _parser(parser_language)
        source = text.encode("utf-8")
        tree = parser.parse(source)
    except (ImportError, OSError, RuntimeError, ValueError):
        return None

    # Traverse once and reuse the node table for every symbol.  Rewalking a
    # large JavaScript subtree once for calls and again for references for each
    # function was quadratic and can destabilize the native bindings.
    all_nodes = [
        (node, node.start_byte, node.end_byte)
        for node in _walk(tree.root_node)
    ]
    call_entries = _collect_call_entries(all_nodes, source)
    reference_entries = _collect_reference_entries(all_nodes, source)
    imports = _extract_imports(tree.root_node, source, nodes=all_nodes)
    symbols: list[Symbol] = []
    for node, _start, _end in all_nodes:
        if node.type in DEFINITION_TYPES:
            name_node = node.child_by_field_name("name")
            if name_node is None:
                continue
            name = _text(name_node, source)
            if not name:
                continue
            symbols.append(
                Symbol(
                    name=name,
                    kind=DEFINITION_TYPES[node.type],
                    start_line=node.start_point.row + 1,
                    end_line=max(node.end_point.row + 1, node.start_point.row + 1),
                    calls=_calls_in_node(node, call_entries),
                    references=_references_in_node(node, reference_entries, excluded={name}),
                    inherits=_extract_inheritance(node, source, nodes=all_nodes),
                    qualified_name=_qualified_name(node, name, source),
                )
            )
        elif node.type == "variable_declarator":
            name_node = node.child_by_field_name("name")
            value_node = node.child_by_field_name("value")
            if (
                name_node is None
                or value_node is None
                or value_node.type not in FUNCTION_VALUE_TYPES
            ):
                continue
            name = _text(name_node, source)
            symbols.append(
                Symbol(
                    name=name,
                    kind="function",
                    start_line=node.start_point.row + 1,
                    end_line=max(node.end_point.row + 1, node.start_point.row + 1),
                    calls=_calls_in_node(value_node, call_entries),
                    references=_references_in_node(value_node, reference_entries, excluded={name}),
                    qualified_name=name,
                )
            )

        route = _route_symbol(node, source)
        if route is not None:
            symbols.append(route)

    return SourceAnalysis(
        language=language,
        imports=_dedupe(imports),
        symbols=_dedupe_symbols(symbols),
        parser_backend=f"tree-sitter:{parser_language}",
    )


def _walk(node: Any) -> Iterator[Any]:
    """Traverse a Tree-sitter tree without consuming the Python call stack.

    Generated JavaScript and deeply nested expressions can produce trees deep
    enough for the recursive implementation to overflow inside the native
    Tree-sitter bindings.  An explicit stack is both safer and measurably
    cheaper because it avoids one Python frame per syntax node.
    """
    nodes: list[Any] = []
    stack = [node]
    while stack:
        current = stack.pop()
        nodes.append(current)
        stack.extend(reversed(current.children))
    return iter(nodes)


def _text(node: Any, source: bytes) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _extract_imports(
    root: Any,
    source: bytes,
    *,
    nodes: list[tuple[Any, int, int]] | None = None,
) -> list[str]:
    imports: list[str] = []
    iterable = (item[0] for item in nodes) if nodes is not None else _walk(root)
    for node in iterable:
        if node.type == "import_statement":
            source_node = node.child_by_field_name("source")
            if source_node is not None:
                imports.append(_strip_string(_text(source_node, source)))
        elif node.type == "call_expression":
            function_node = node.child_by_field_name("function")
            arguments = node.child_by_field_name("arguments")
            if function_node is None or arguments is None:
                continue
            if _text(function_node, source) not in {"require", "import"}:
                continue
            string_node = next(
                (
                    child
                    for child in arguments.named_children
                    if child.type in {"string", "template_string"}
                ),
                None,
            )
            if string_node is not None:
                imports.append(_strip_string(_text(string_node, source)))
    return imports


def _extract_calls(
    node: Any,
    source: bytes,
    *,
    nodes: list[tuple[Any, int, int]] | None = None,
) -> list[str]:
    calls: list[str] = []
    descendants = _descendants(node, nodes) if nodes is not None else _walk(node)
    for child in descendants:
        if child.type != "call_expression":
            continue
        function_node = child.child_by_field_name("function")
        if function_node is None:
            continue
        name = _call_name(function_node, source)
        if name and name.lower() not in {
            "if",
            "for",
            "while",
            "switch",
            "catch",
            "require",
            "import",
        }:
            calls.append(name)
    return _dedupe(calls)


def _collect_call_entries(
    nodes: list[tuple[Any, int, int]],
    source: bytes,
) -> list[tuple[int, int, str]]:
    entries: list[tuple[int, int, str]] = []
    for node, start, end in nodes:
        if node.type != "call_expression":
            continue
        function_node = node.child_by_field_name("function")
        if function_node is None:
            continue
        name = _call_name(function_node, source)
        if name and name.lower() not in {
            "if", "for", "while", "switch", "catch", "require", "import",
        }:
            entries.append((start, end, name))
    return entries


def _calls_in_node(node: Any, entries: list[tuple[int, int, str]]) -> list[str]:
    start = node.start_byte
    end = node.end_byte
    return _dedupe(name for call_start, call_end, name in entries if call_start >= start and call_end <= end)


def _call_name(node: Any, source: bytes) -> str:
    if node.type in {
        "identifier",
        "property_identifier",
        "private_property_identifier",
    }:
        return _text(node, source)
    if node.type in {"member_expression", "subscript_expression"}:
        property_node = node.child_by_field_name(
            "property"
        ) or node.child_by_field_name("index")
        if property_node is not None:
            return _strip_string(_text(property_node, source))
    text = _text(node, source)
    return text.rsplit(".", 1)[-1] if text else ""


def _extract_references(
    node: Any,
    source: bytes,
    *,
    excluded: set[str],
    nodes: list[tuple[Any, int, int]] | None = None,
) -> list[str]:
    references = []
    descendants = _descendants(node, nodes) if nodes is not None else _walk(node)
    for child in descendants:
        if child.type not in {"identifier", "type_identifier"}:
            continue
        value = _text(child, source)
        if value and value not in excluded:
            references.append(value)
    return _dedupe(references)


def _collect_reference_entries(
    nodes: list[tuple[Any, int, int]],
    source: bytes,
) -> list[tuple[int, int, str]]:
    return [
        (start, end, source[start:end].decode("utf-8", errors="replace"))
        for node, start, end in nodes
        if node.type in {"identifier", "type_identifier"}
    ]


def _references_in_node(
    node: Any,
    entries: list[tuple[int, int, str]],
    *,
    excluded: set[str],
) -> list[str]:
    start = node.start_byte
    end = node.end_byte
    return _dedupe(
        value
        for reference_start, reference_end, value in entries
        if reference_start >= start and reference_end <= end and value and value not in excluded
    )


def _extract_inheritance(
    node: Any,
    source: bytes,
    *,
    nodes: list[tuple[Any, int, int]] | None = None,
) -> list[str]:
    if node.type != "class_declaration":
        return []
    heritage = node.child_by_field_name("superclass")
    if heritage is not None:
        return [_text(heritage, source)]
    values: list[str] = []
    for child in node.named_children:
        if child.type in {"class_heritage", "extends_clause", "implements_clause"}:
            values.extend(
                _text(descendant, source)
                for descendant in (_descendants(child, nodes) if nodes is not None else _walk(child))
                if descendant.type in {"identifier", "type_identifier"}
            )
    return _dedupe(values)


def _descendants(node: Any, nodes: list[tuple[Any, int, int]]) -> Iterator[Any]:
    """Yield nodes contained by *node* from a repository-wide node table."""
    start = node.start_byte
    end = node.end_byte
    return (
        candidate
        for candidate, candidate_start, candidate_end in nodes
        if candidate_start >= start and candidate_end <= end
    )


def _qualified_name(node: Any, name: str, source: bytes) -> str:
    if node.type != "method_definition":
        return name
    parent = node.parent
    while parent is not None:
        if parent.type == "class_declaration":
            class_name = parent.child_by_field_name("name")
            if class_name is not None:
                return f"{_text(class_name, source)}.{name}"
        parent = parent.parent
    return name


def _route_symbol(node: Any, source: bytes) -> Symbol | None:
    if node.type != "call_expression":
        return None
    function_node = node.child_by_field_name("function")
    arguments = node.child_by_field_name("arguments")
    if (
        function_node is None
        or arguments is None
        or function_node.type != "member_expression"
    ):
        return None
    owner_node = function_node.child_by_field_name("object")
    method_node = function_node.child_by_field_name("property")
    if owner_node is None or method_node is None:
        return None
    owner = _text(owner_node, source)
    method = _text(method_node, source).lower()
    if method not in ROUTE_METHODS or not _is_route_owner(owner):
        return None
    named_arguments = list(arguments.named_children)
    if not named_arguments or named_arguments[0].type not in {
        "string",
        "template_string",
    }:
        return None
    route_path = _strip_string(_text(named_arguments[0], source))
    handlers = [
        _text(child, source)
        for child in named_arguments[1:]
        if child.type in {"identifier", "property_identifier"}
    ]
    safe_route = _safe_route_name(route_path)
    return Symbol(
        name=f"{method}_{safe_route}",
        kind="route",
        start_line=node.start_point.row + 1,
        end_line=max(node.end_point.row + 1, node.start_point.row + 1),
        calls=_dedupe(handlers),
        references=_dedupe(handlers),
        qualified_name=f"{owner}.{method}",
        route_path=route_path,
        handler_names=_dedupe(handlers),
    )


def _is_route_owner(owner: str) -> bool:
    tail = owner.rsplit(".", 1)[-1]
    lowered = tail.lower()
    return lowered in {"app", "router", "server"} or lowered.endswith(
        ("router", "routes", "controller")
    )


def _strip_string(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'", "`"}:
        return value[1:-1]
    return value


def _safe_route_name(route_path: str) -> str:
    import re

    value = re.sub(r"[^A-Za-z0-9_]+", "_", route_path.strip("/")) or "root"
    return value.strip("_") or "root"


def _dedupe(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = value.strip()
        key = normalized.lower()
        if normalized and key not in seen:
            seen.add(key)
            result.append(normalized)
    return result


def _dedupe_symbols(symbols: list[Symbol]) -> list[Symbol]:
    result: list[Symbol] = []
    seen: set[tuple[str, int, str]] = set()
    for symbol in sorted(
        symbols, key=lambda item: (item.start_line, item.end_line, item.kind, item.name)
    ):
        key = (symbol.name.lower(), symbol.start_line, symbol.kind)
        if key not in seen:
            seen.add(key)
            result.append(symbol)
    return result


def _looks_like_tsx(text: str) -> bool:
    return "</" in text or "return (" in text and "<" in text and ">" in text
