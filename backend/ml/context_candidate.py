from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

from backend.tools.workspace_search_tool import WorkspaceFileSnapshot, WorkspaceSearchResult
from backend.tools.workspace_semantic_tool import WorkspaceSemanticResult


MAX_CHUNK_CHARS = 2200
FALLBACK_WINDOW_LINES = 80
MAX_CHUNKS_PER_FILE = 12
MAX_TOTAL_WORKSPACE_CHUNKS = 36
MAX_CALL_CHAIN_CHUNKS = 24

JS_SYMBOL_PATTERN = re.compile(
    r"^\s*(?:export\s+)?(?:async\s+)?(?:function|class)\s+([A-Za-z_$][\w$]*)"
    r"|^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=",
    re.MULTILINE,
)
VUE_BLOCK_PATTERN = re.compile(r"<(template|script|style)[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE)
MARKDOWN_HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)


@dataclass
class ContextCandidateChunk:
    """
    统一表示可参与注意力重排的上下文片段。
    """

    relative_path: str
    identifier: str
    title: str
    content: str
    chunk_type: str
    location: str
    retrieval_score: float


def build_workspace_context_chunks(
    search_result: WorkspaceSearchResult | None,
    semantic_result: WorkspaceSemanticResult | None = None,
    enable_call_chain: bool = True,
) -> list[ContextCandidateChunk]:
    """
    将工作区候选文件拆成函数、类、Markdown 段落或固定窗口 chunk。
    """

    if not search_result:
        return []

    semantic_by_path = {
        match.relative_path.replace("\\", "/").lower(): match
        for match in (semantic_result.matches if semantic_result else [])
    }

    chunks: list[ContextCandidateChunk] = []
    for snapshot in search_result.candidate_files:
        relative_path = snapshot.relative_path.replace("\\", "/")
        semantic_match = semantic_by_path.get(relative_path.lower())
        semantic_reason = semantic_match.reason if semantic_match else ""
        semantic_score = semantic_match.score if semantic_match else 0.0
        retrieval_score = min(max(float(snapshot.score), 0.0) / 120.0, 0.45)
        retrieval_score = max(retrieval_score, semantic_score)

        file_chunks = split_file_into_chunks(snapshot, retrieval_score)
        for chunk in file_chunks[:MAX_CHUNKS_PER_FILE]:
            if semantic_reason:
                chunk.content = (
                    f"Path: {relative_path}\n"
                    f"Semantic reason: {semantic_reason}\n"
                    f"{chunk.content}"
                )
            chunks.append(chunk)

    if enable_call_chain:
        chunks = [*chunks, *expand_python_call_chain_chunks(chunks)]

    return chunks[:MAX_TOTAL_WORKSPACE_CHUNKS]


def split_file_into_chunks(
    snapshot: WorkspaceFileSnapshot,
    retrieval_score: float,
) -> list[ContextCandidateChunk]:
    relative_path = snapshot.relative_path.replace("\\", "/")
    suffix = Path(relative_path).suffix.lower()
    content = snapshot.full_content or snapshot.excerpt

    if suffix == ".py":
        chunks = split_python_file(relative_path, content, retrieval_score)
    elif suffix in {".ts", ".tsx", ".js", ".jsx"}:
        chunks = split_javascript_like_file(relative_path, content, retrieval_score)
    elif suffix == ".vue":
        chunks = split_vue_file(relative_path, content, retrieval_score)
    elif suffix in {".md", ".txt"}:
        chunks = split_markdown_file(relative_path, content, retrieval_score)
    else:
        chunks = split_by_line_windows(relative_path, content, "text", retrieval_score)

    if chunks:
        return chunks

    fallback_content = snapshot.excerpt or content
    return [
        build_chunk(
            relative_path=relative_path,
            title=relative_path,
            content=fallback_content,
            chunk_type="file_excerpt",
            start_line=1,
            end_line=max(1, fallback_content.count("\n") + 1),
            retrieval_score=retrieval_score,
        )
    ]


def split_python_file(
    relative_path: str,
    content: str,
    retrieval_score: float,
) -> list[ContextCandidateChunk]:
    lines = content.splitlines()
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return split_by_line_windows(relative_path, content, "python_window", retrieval_score)

    chunks: list[ContextCandidateChunk] = []
    class_overviews: list[ContextCandidateChunk] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            chunks.append(
                build_python_node_chunk(
                    relative_path=relative_path,
                    lines=lines,
                    node=node,
                    title=f"{relative_path}::{node.name}",
                    chunk_type="function",
                    retrieval_score=retrieval_score,
                )
            )
            continue

        if not isinstance(node, ast.ClassDef):
            continue

        method_nodes = [
            child
            for child in node.body
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        if not method_nodes:
            chunks.append(
                build_python_node_chunk(
                    relative_path=relative_path,
                    lines=lines,
                    node=node,
                    title=f"{relative_path}::{node.name}",
                    chunk_type="class",
                    retrieval_score=retrieval_score,
                )
            )
            continue

        for method_node in method_nodes:
            start_line, end_line = get_python_node_line_span(method_node)
            method_content = "\n".join(lines[start_line - 1 : end_line])
            class_context = build_python_class_context_prefix(node, method_nodes)
            chunks.append(
                build_chunk(
                    relative_path=relative_path,
                    title=f"{relative_path}::{node.name}.{method_node.name}",
                    content=f"{class_context}\n{method_content}",
                    chunk_type="method",
                    start_line=start_line,
                    end_line=end_line,
                    retrieval_score=retrieval_score,
                )
            )

        class_overview = build_python_class_overview_chunk(
            relative_path=relative_path,
            lines=lines,
            class_node=node,
            method_nodes=method_nodes,
            retrieval_score=retrieval_score,
        )
        if class_overview:
            class_overviews.append(class_overview)

    chunks.extend(class_overviews)
    return chunks or split_by_line_windows(relative_path, content, "python_window", retrieval_score)


def build_python_node_chunk(
    *,
    relative_path: str,
    lines: list[str],
    node: ast.AST,
    title: str,
    chunk_type: str,
    retrieval_score: float,
) -> ContextCandidateChunk:
    start_line, end_line = get_python_node_line_span(node)
    chunk_content = "\n".join(lines[start_line - 1 : end_line])
    return build_chunk(
        relative_path=relative_path,
        title=title,
        content=chunk_content,
        chunk_type=chunk_type,
        start_line=start_line,
        end_line=end_line,
        retrieval_score=retrieval_score,
    )


def build_python_class_context_prefix(
    class_node: ast.ClassDef,
    method_nodes: list[ast.FunctionDef | ast.AsyncFunctionDef],
) -> str:
    base_names = [name.id for name in class_node.bases if isinstance(name, ast.Name)]
    base_suffix = f"({', '.join(base_names)})" if base_names else ""
    method_names = ", ".join(method.name for method in method_nodes)
    docstring = ast.get_docstring(class_node) or ""
    prefix_lines = [f"class {class_node.name}{base_suffix}:"]
    if docstring:
        first_line = docstring.strip().splitlines()[0]
        prefix_lines.append(f'    """{first_line}"""')
    if method_names:
        prefix_lines.append(f"    # methods: {method_names}")
    return "\n".join(prefix_lines)


def build_python_class_overview_chunk(
    *,
    relative_path: str,
    lines: list[str],
    class_node: ast.ClassDef,
    method_nodes: list[ast.FunctionDef | ast.AsyncFunctionDef],
    retrieval_score: float,
) -> ContextCandidateChunk | None:
    start_line, _ = get_python_node_line_span(class_node)
    class_line = max(getattr(class_node, "lineno", start_line), start_line)
    overview_lines = lines[start_line - 1 : class_line]
    docstring_node = get_python_docstring_node(class_node)
    end_line = class_line
    if docstring_node:
        doc_start, doc_end = get_python_node_line_span(docstring_node)
        overview_lines.extend(lines[doc_start - 1 : doc_end])
        end_line = doc_end

    method_names = ", ".join(method.name for method in method_nodes)
    if method_names:
        indent = " " * (get_line_indent(lines[class_line - 1]) + 4)
        overview_lines.append(f"{indent}# methods: {method_names}")

    if len(overview_lines) <= 1:
        return None

    return build_chunk(
        relative_path=relative_path,
        title=f"{relative_path}::{class_node.name}",
        content="\n".join(overview_lines),
        chunk_type="class_overview",
        start_line=start_line,
        end_line=end_line,
        retrieval_score=retrieval_score,
    )


def get_python_docstring_node(node: ast.ClassDef) -> ast.Expr | None:
    if not node.body:
        return None
    first_child = node.body[0]
    if not isinstance(first_child, ast.Expr):
        return None
    if isinstance(first_child.value, ast.Constant) and isinstance(first_child.value.value, str):
        return first_child
    return None


def get_python_node_line_span(node: ast.AST) -> tuple[int, int]:
    start_line = max(getattr(node, "lineno", 1), 1)
    for decorator in getattr(node, "decorator_list", []):
        start_line = min(start_line, max(getattr(decorator, "lineno", start_line), 1))

    end_line = max(getattr(node, "end_lineno", start_line), start_line)
    return start_line, end_line


def get_line_indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def split_javascript_like_file(
    relative_path: str,
    content: str,
    retrieval_score: float,
) -> list[ContextCandidateChunk]:
    lines = content.splitlines()
    matches = list(JS_SYMBOL_PATTERN.finditer(content))
    if not matches:
        return split_by_line_windows(relative_path, content, "code_window", retrieval_score)

    line_starts = build_line_start_offsets(content)
    chunks: list[ContextCandidateChunk] = []
    for index, match in enumerate(matches):
        symbol_name = next(group for group in match.groups() if group)
        start_line = offset_to_line(line_starts, match.start())
        end_offset = matches[index + 1].start() if index + 1 < len(matches) else len(content)
        end_line = offset_to_line(line_starts, end_offset)
        chunk_content = "\n".join(lines[start_line - 1 : end_line])
        chunks.append(
            build_chunk(
                relative_path=relative_path,
                title=f"{relative_path}::{symbol_name}",
                content=chunk_content,
                chunk_type="symbol",
                start_line=start_line,
                end_line=end_line,
                retrieval_score=retrieval_score,
            )
        )

    return chunks


def split_vue_file(
    relative_path: str,
    content: str,
    retrieval_score: float,
) -> list[ContextCandidateChunk]:
    line_starts = build_line_start_offsets(content)
    chunks: list[ContextCandidateChunk] = []
    for match in VUE_BLOCK_PATTERN.finditer(content):
        block_type = match.group(1).lower()
        start_line = offset_to_line(line_starts, match.start())
        end_line = offset_to_line(line_starts, match.end())
        chunks.append(
            build_chunk(
                relative_path=relative_path,
                title=f"{relative_path}::<{block_type}>",
                content=match.group(0),
                chunk_type=f"vue_{block_type}",
                start_line=start_line,
                end_line=end_line,
                retrieval_score=retrieval_score,
            )
        )

    return chunks or split_by_line_windows(relative_path, content, "vue_window", retrieval_score)


def split_markdown_file(
    relative_path: str,
    content: str,
    retrieval_score: float,
) -> list[ContextCandidateChunk]:
    matches = list(MARKDOWN_HEADING_PATTERN.finditer(content))
    if not matches:
        return split_by_line_windows(relative_path, content, "markdown_window", retrieval_score)

    line_starts = build_line_start_offsets(content)
    chunks: list[ContextCandidateChunk] = []
    for index, match in enumerate(matches):
        heading = match.group(2).strip()
        start_line = offset_to_line(line_starts, match.start())
        end_offset = matches[index + 1].start() if index + 1 < len(matches) else len(content)
        end_line = offset_to_line(line_starts, end_offset)
        chunk_content = content[match.start() : end_offset]
        chunks.append(
            build_chunk(
                relative_path=relative_path,
                title=f"{relative_path}::{heading}",
                content=chunk_content,
                chunk_type="markdown_section",
                start_line=start_line,
                end_line=end_line,
                retrieval_score=retrieval_score,
            )
        )

    return chunks


def split_by_line_windows(
    relative_path: str,
    content: str,
    chunk_type: str,
    retrieval_score: float,
) -> list[ContextCandidateChunk]:
    lines = content.splitlines()
    if not lines:
        return []

    chunks: list[ContextCandidateChunk] = []
    for start_index in range(0, len(lines), FALLBACK_WINDOW_LINES):
        end_index = min(start_index + FALLBACK_WINDOW_LINES, len(lines))
        chunk_content = "\n".join(lines[start_index:end_index])
        chunks.append(
            build_chunk(
                relative_path=relative_path,
                title=f"{relative_path}::L{start_index + 1}-L{end_index}",
                content=chunk_content,
                chunk_type=chunk_type,
                start_line=start_index + 1,
                end_line=end_index,
                retrieval_score=retrieval_score,
            )
        )
        if len(chunks) >= MAX_CHUNKS_PER_FILE:
            break

    return chunks


def expand_python_call_chain_chunks(
    chunks: list[ContextCandidateChunk],
) -> list[ContextCandidateChunk]:
    """
    基于 Python 调用关系追加一跳调用链候选。

    这一层不替代 embedding 和 attention，只负责把“入口方法调用到的底层实现”
    放进候选池，后续仍由注意力模块决定是否选入 Prompt。
    """

    python_chunks = [chunk for chunk in chunks if chunk.relative_path.lower().endswith(".py")]
    if not python_chunks:
        return []

    symbol_index = build_python_symbol_index(python_chunks)
    class_attribute_types = infer_python_class_attribute_types(python_chunks)
    expanded: list[ContextCandidateChunk] = []
    seen: set[tuple[str, str]] = set()

    for caller in python_chunks:
        if caller.chunk_type not in {"function", "method", "class", "python_window"}:
            continue

        call_symbols = extract_python_call_symbols(caller, class_attribute_types)
        for symbol in call_symbols:
            target = resolve_python_call_target(symbol, symbol_index)
            if not target or target.identifier == caller.identifier:
                continue

            key = (caller.identifier, target.identifier)
            if key in seen:
                continue
            seen.add(key)
            expanded.append(build_call_chain_chunk(caller, target, symbol))
            if len(expanded) >= MAX_CALL_CHAIN_CHUNKS:
                return expanded

    return expanded


def build_python_symbol_index(
    chunks: list[ContextCandidateChunk],
) -> dict[str, list[ContextCandidateChunk]]:
    index: dict[str, list[ContextCandidateChunk]] = {}

    for chunk in chunks:
        symbol = chunk.title.split("::", 1)[-1].strip()
        if not symbol:
            continue

        add_symbol_index_entry(index, symbol, chunk)
        add_symbol_index_entry(index, symbol.replace("::", "."), chunk)
        if "." in symbol:
            add_symbol_index_entry(index, symbol.split(".")[-1], chunk)

    return index


def add_symbol_index_entry(
    index: dict[str, list[ContextCandidateChunk]],
    symbol: str,
    chunk: ContextCandidateChunk,
) -> None:
    normalized = normalize_symbol(symbol)
    if not normalized:
        return
    index.setdefault(normalized, []).append(chunk)


def infer_python_class_attribute_types(
    chunks: list[ContextCandidateChunk],
) -> dict[str, dict[str, str]]:
    class_attribute_types: dict[str, dict[str, str]] = {}

    for chunk in chunks:
        code = extract_python_code_from_chunk(chunk.content)
        try:
            tree = ast.parse(code)
        except SyntaxError:
            continue

        for class_node in [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]:
            attributes = class_attribute_types.setdefault(class_node.name, {})
            for node in ast.walk(class_node):
                if isinstance(node, ast.AnnAssign):
                    target = node.target
                    if is_self_attribute(target):
                        inferred = infer_type_name_from_annotation(node.annotation)
                        if inferred:
                            attributes[target.attr] = inferred
                elif isinstance(node, ast.Assign):
                    inferred = infer_type_name_from_value(node.value)
                    if not inferred:
                        continue
                    for target in node.targets:
                        if is_self_attribute(target):
                            attributes[target.attr] = inferred

    return class_attribute_types


def extract_python_call_symbols(
    chunk: ContextCandidateChunk,
    class_attribute_types: dict[str, dict[str, str]],
) -> list[str]:
    code = extract_python_code_from_chunk(chunk.content)
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []

    enclosing_class = first_class_name(tree)
    local_types = infer_python_local_types(tree, enclosing_class, class_attribute_types)
    symbols: list[str] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        symbol = resolve_python_call_symbol(
            node.func,
            enclosing_class,
            class_attribute_types,
            local_types,
        )
        if symbol:
            symbols.append(symbol)

    return dedupe_preserve_order(symbols)


def infer_python_local_types(
    tree: ast.AST,
    enclosing_class: str | None,
    class_attribute_types: dict[str, dict[str, str]],
) -> dict[str, str]:
    local_types: dict[str, str] = {}
    container_types: dict[str, str] = {}

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for argument in node.args.args:
                inferred = infer_type_name_from_annotation(argument.annotation)
                if inferred:
                    local_types[argument.arg] = inferred
                    if is_container_annotation(argument.annotation):
                        container_types[argument.arg] = inferred
        elif isinstance(node, ast.AnnAssign):
            inferred = infer_type_name_from_annotation(node.annotation)
            if not inferred:
                continue
            if isinstance(node.target, ast.Name):
                local_types[node.target.id] = inferred
                if is_container_annotation(node.annotation):
                    container_types[node.target.id] = inferred
        elif isinstance(node, ast.Assign):
            inferred = infer_type_name_from_value(node.value)
            if not inferred:
                continue
            for target in node.targets:
                if isinstance(target, ast.Name):
                    local_types[target.id] = inferred
        elif isinstance(node, ast.For):
            iter_type = infer_for_iter_type(node.iter, enclosing_class, class_attribute_types, container_types)
            if iter_type and isinstance(node.target, ast.Name):
                local_types[node.target.id] = iter_type

    return local_types


def infer_for_iter_type(
    node: ast.AST,
    enclosing_class: str | None,
    class_attribute_types: dict[str, dict[str, str]],
    container_types: dict[str, str],
) -> str:
    if isinstance(node, ast.Name):
        return container_types.get(node.id, "")

    if (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "self"
        and enclosing_class
    ):
        return class_attribute_types.get(enclosing_class, {}).get(node.attr, "")

    return ""


def resolve_python_call_symbol(
    node: ast.AST,
    enclosing_class: str | None,
    class_attribute_types: dict[str, dict[str, str]],
    local_types: dict[str, str],
) -> str:
    if isinstance(node, ast.Name):
        return node.id

    if not isinstance(node, ast.Attribute):
        return ""

    method_name = node.attr
    value = node.value
    if isinstance(value, ast.Name):
        if value.id in local_types:
            return f"{local_types[value.id]}.{method_name}"
        if value.id and value.id[0].isupper():
            return f"{value.id}.{method_name}"
        return method_name

    if (
        isinstance(value, ast.Attribute)
        and isinstance(value.value, ast.Name)
        and value.value.id == "self"
        and enclosing_class
    ):
        attr_type = class_attribute_types.get(enclosing_class, {}).get(value.attr, "")
        if attr_type:
            return f"{attr_type}.{method_name}"

    if isinstance(value, ast.Name) and value.id == "self" and enclosing_class:
        return f"{enclosing_class}.{method_name}"

    return method_name


def resolve_python_call_target(
    symbol: str,
    symbol_index: dict[str, list[ContextCandidateChunk]],
) -> ContextCandidateChunk | None:
    normalized = normalize_symbol(symbol)
    candidates = symbol_index.get(normalized, [])
    if candidates:
        return choose_best_call_target(candidates)

    if "." in normalized:
        candidates = symbol_index.get(normalized.split(".")[-1], [])
        if candidates:
            return choose_best_call_target(candidates)

    return None


def choose_best_call_target(
    candidates: list[ContextCandidateChunk],
) -> ContextCandidateChunk | None:
    priority = {
        "method": 0,
        "function": 1,
        "class_overview": 2,
        "class": 3,
    }
    return sorted(
        candidates,
        key=lambda chunk: (priority.get(chunk.chunk_type, 9), len(chunk.content)),
    )[0] if candidates else None


def build_call_chain_chunk(
    caller: ContextCandidateChunk,
    target: ContextCandidateChunk,
    symbol: str,
) -> ContextCandidateChunk:
    safe_caller = re.sub(r"[^A-Za-z0-9_.-]+", "_", caller.title)[-90:]
    retrieval_score = min(max(target.retrieval_score, caller.retrieval_score + 0.18), 0.98)
    return ContextCandidateChunk(
        relative_path=target.relative_path,
        identifier=f"{target.identifier}#call-chain-from-{safe_caller}",
        title=f"{target.title} <- {caller.title}",
        content=(
            f"Path: {target.relative_path}\n"
            f"Chunk type: call_chain_{target.chunk_type}\n"
            f"Location: {target.location}\n"
            f"Call chain reason: `{caller.title}` calls `{symbol}`, so this callee is added as a derived context candidate.\n"
            f"Caller: {caller.title} ({caller.location})\n"
            f"Callee: {target.title} ({target.location})\n"
            f"{target.content}"
        ),
        chunk_type=f"call_chain_{target.chunk_type}",
        location=target.location,
        retrieval_score=retrieval_score,
    )


def extract_python_code_from_chunk(content: str) -> str:
    code_lines: list[str] = []
    skipped_prefixes = (
        "Path:",
        "Semantic reason:",
        "Chunk type:",
        "Location:",
        "Call chain reason:",
        "Caller:",
        "Callee:",
    )
    for line in content.splitlines():
        if any(line.startswith(prefix) for prefix in skipped_prefixes):
            continue
        if line.startswith("...["):
            continue
        code_lines.append(line)
    return "\n".join(code_lines).strip()


def first_class_name(tree: ast.AST) -> str | None:
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            return node.name
    return None


def is_self_attribute(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "self"
    )


def infer_type_name_from_annotation(annotation: ast.AST | None) -> str:
    if annotation is None:
        return ""
    try:
        raw = ast.unparse(annotation)
    except Exception:
        raw = ""
    return infer_type_name_from_text(raw)


def infer_type_name_from_value(value: ast.AST) -> str:
    if isinstance(value, ast.Call):
        if isinstance(value.func, ast.Name):
            return value.func.id
        if isinstance(value.func, ast.Attribute):
            return value.func.attr
    if isinstance(value, ast.BoolOp):
        for child in value.values:
            inferred = infer_type_name_from_value(child)
            if inferred:
                return inferred
    return ""


def infer_type_name_from_text(text: str) -> str:
    matches = re.findall(r"\b[A-Z][A-Za-z0-9_]*\b", text)
    if not matches:
        return ""
    for match in matches:
        if match not in {"None", "Path", "Literal"}:
            return match
    return matches[0]


def is_container_annotation(annotation: ast.AST | None) -> bool:
    if annotation is None:
        return False
    try:
        raw = ast.unparse(annotation).lower()
    except Exception:
        return False
    return any(token in raw for token in ["list[", "dict[", "set[", "tuple[", "sequence[", "iterable["])


def dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        normalized = normalize_symbol(value)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(value)
    return deduped


def normalize_symbol(symbol: str) -> str:
    return symbol.replace("::", ".").strip().lower()


def build_chunk(
    *,
    relative_path: str,
    title: str,
    content: str,
    chunk_type: str,
    start_line: int,
    end_line: int,
    retrieval_score: float,
) -> ContextCandidateChunk:
    cleaned_content = truncate_chunk(content)
    location = f"L{start_line}-L{end_line}"
    identifier = f"{relative_path}#{location}"
    return ContextCandidateChunk(
        relative_path=relative_path,
        identifier=identifier,
        title=title,
        content=(
            f"Path: {relative_path}\n"
            f"Chunk type: {chunk_type}\n"
            f"Location: {location}\n"
            f"{cleaned_content}"
        ),
        chunk_type=chunk_type,
        location=location,
        retrieval_score=retrieval_score,
    )


def truncate_chunk(content: str) -> str:
    cleaned = content.strip()
    if len(cleaned) <= MAX_CHUNK_CHARS:
        return cleaned
    return cleaned[:MAX_CHUNK_CHARS] + "\n...[chunk truncated]"


def build_line_start_offsets(content: str) -> list[int]:
    offsets = [0]
    for index, char in enumerate(content):
        if char == "\n":
            offsets.append(index + 1)
    return offsets


def offset_to_line(line_starts: list[int], offset: int) -> int:
    low = 0
    high = len(line_starts) - 1
    while low <= high:
        middle = (low + high) // 2
        if line_starts[middle] <= offset:
            low = middle + 1
        else:
            high = middle - 1
    return max(1, high + 1)
