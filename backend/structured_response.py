import re
from dataclasses import dataclass, field

from backend.models import AgentActionKind


@dataclass
class ParsedAction:
    """保存单个结构化动作。"""

    kind: AgentActionKind
    target_file: str
    summary: str
    updated_content: str


@dataclass
class ParsedActionPlanResponse:
    """保存模型返回的项目级变更方案。"""

    assistant_reply: str = ""
    proposal_summary: str = ""
    actions: list[ParsedAction] = field(default_factory=list)


def parse_action_plan_response(content: str) -> ParsedActionPlanResponse:
    """从模型返回文本里提取结构化动作方案。"""
    normalized_content = _normalize_markup(content)
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


def _extract_tag(content: str, tag_name: str) -> str:
    pattern = re.compile(rf"<{tag_name}>\s*(.*?)\s*</{tag_name}>", re.DOTALL | re.IGNORECASE)
    match = pattern.search(content)
    if not match:
        return ""
    return match.group(1)


def _cleanup_file_content(content: str) -> str:
    cleaned = content.strip("\r\n")
    fence_match = re.fullmatch(r"```[^\n]*\n(.*?)\n```", cleaned, re.DOTALL)
    if fence_match:
        return fence_match.group(1).strip("\r\n")
    return cleaned


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
        normalized = re.sub(rf"(?<!<){tag}>", f"<{tag}>", normalized, flags=re.IGNORECASE)
        normalized = re.sub(rf"\({tag}>", f"<{tag}>", normalized, flags=re.IGNORECASE)
        normalized = re.sub(rf"\({tag}\s*>", f"<{tag}>", normalized, flags=re.IGNORECASE)

    return normalized


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
