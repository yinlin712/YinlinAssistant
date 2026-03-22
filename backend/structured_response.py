import re
from dataclasses import dataclass, field

from backend.models import AgentActionKind

# 文件说明：
# 本文件负责解析大模型返回的文本结果。
# 当前主要支持两类结果：
# 1. 多文件结构化动作方案
# 2. 单文件完整内容改写结果


# 数据说明：
# 表示一个已经解析完成的结构化动作。
@dataclass
class ParsedAction:
    kind: AgentActionKind
    target_file: str
    summary: str
    updated_content: str


# 数据说明：
# 表示项目级动作规划的解析结果。
@dataclass
class ParsedActionPlanResponse:
    assistant_reply: str = ""
    proposal_summary: str = ""
    actions: list[ParsedAction] = field(default_factory=list)


# 数据说明：
# 表示单文件改写模式的解析结果。
@dataclass
class ParsedSingleFileResponse:
    summary: str = ""
    updated_content: str = ""


# 函数说明：
# 从模型输出中提取项目级动作规划结果。
def parse_action_plan_response(content: str) -> ParsedActionPlanResponse:
    normalized_content = _normalize_markup(_unwrap_fenced_content(content))
    actions: list[ParsedAction] = []

    for block in re.findall(r"<action>\s*(.*?)\s*</action>", normalized_content, flags=re.DOTALL | re.IGNORECASE):
        kind = _normalize_kind(_extract_tag(block, "kind"))
        target_file = _extract_tag(block, "target_file").strip()
        summary = _extract_tag(block, "summary").strip()
        updated_content = _cleanup_file_content(
            _extract_tag(block, "updated_content") or _extract_tag(block, "updated_file")
        )

        if not kind or not target_file or not updated_content:
            continue

        actions.append(
            ParsedAction(
                kind=kind,
                target_file=target_file,
                summary=summary,
                updated_content=updated_content,
            )
        )

    return ParsedActionPlanResponse(
        assistant_reply=_extract_tag(normalized_content, "assistant_reply").strip(),
        proposal_summary=_extract_tag(normalized_content, "proposal_summary").strip(),
        actions=actions,
    )


# 函数说明：
# 从模型输出中提取单文件完整内容。
def parse_single_file_response(content: str) -> ParsedSingleFileResponse:
    normalized_content = _normalize_markup(_unwrap_fenced_content(content))
    summary = _extract_tag(normalized_content, "summary").strip()
    updated_content = _cleanup_file_content(
        _extract_tag(normalized_content, "updated_content") or _extract_tag(normalized_content, "updated_file")
    )

    if not updated_content:
        updated_content = _extract_largest_code_block(normalized_content)

    if not updated_content:
        updated_content = re.sub(
            r"<summary>.*?</summary>",
            "",
            normalized_content,
            flags=re.DOTALL | re.IGNORECASE,
        ).strip()

    return ParsedSingleFileResponse(summary=summary, updated_content=updated_content.strip())


# 函数说明：
# 从指定标签中提取文本内容。
def _extract_tag(content: str, tag_name: str) -> str:
    pattern = re.compile(rf"<{tag_name}>\s*(.*?)\s*</{tag_name}>", re.DOTALL | re.IGNORECASE)
    match = pattern.search(content)
    if not match:
        return ""
    return match.group(1)


# 函数说明：
# 清理标签内部的代码块包裹符号。
def _cleanup_file_content(content: str) -> str:
    cleaned = content.strip("\r\n")
    fence_match = re.fullmatch(r"```[^\n]*\n(.*?)\n```", cleaned, re.DOTALL)
    if fence_match:
        return fence_match.group(1).strip("\r\n")
    return cleaned


# 函数说明：
# 如果模型把全部输出包在 Markdown 代码块里，先拆掉外层代码块。
def _unwrap_fenced_content(content: str) -> str:
    stripped = content.strip()
    fence_match = re.fullmatch(r"```[^\n]*\n(.*?)\n```", stripped, re.DOTALL)
    if fence_match:
        return fence_match.group(1).strip()
    return stripped


# 函数说明：
# 在模型返回多个代码块时，取内容最长的一段作为候选文件内容。
def _extract_largest_code_block(content: str) -> str:
    blocks = re.findall(r"```[^\n]*\n(.*?)\n```", content, flags=re.DOTALL)
    if not blocks:
        return ""

    largest_block = max(blocks, key=len)
    return largest_block.strip("\r\n")


# 函数说明：
# 对常见的坏标签格式做轻量归一化处理。
def _normalize_markup(content: str) -> str:
    normalized = content
    known_tags = [
        "assistant_reply",
        "proposal_summary",
        "actions",
        "action",
        "kind",
        "target_file",
        "summary",
        "updated_content",
        "updated_file",
    ]

    for tag in known_tags:
        normalized = re.sub(rf"(?<!<)(?<!/){tag}>", f"<{tag}>", normalized, flags=re.IGNORECASE)
        normalized = re.sub(rf"\({tag}>", f"<{tag}>", normalized, flags=re.IGNORECASE)
        normalized = re.sub(rf"\({tag}\s*>", f"<{tag}>", normalized, flags=re.IGNORECASE)

    return normalized


# 函数说明：
# 将模型给出的动作类型别名映射为统一枚举值。
def _normalize_kind(raw_kind: str) -> AgentActionKind | None:
    normalized = raw_kind.strip().lower().replace("-", "_")

    mapping: dict[str, AgentActionKind] = {
        "create": "create_file",
        "create_file": "create_file",
        "new_file": "create_file",
        "add_file": "create_file",
        "update": "update_file",
        "update_file": "update_file",
        "modify_file": "update_file",
        "rewrite_file": "update_file",
        "update_current_file": "update_file",
        "update_documentation": "update_documentation",
        "documentation": "update_documentation",
        "update_docs": "update_documentation",
        "update_readme": "update_documentation",
        "update_doc": "update_documentation",
    }

    return mapping.get(normalized)
