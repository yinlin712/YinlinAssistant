from backend.models import AgentContextModel
from backend.tools.workspace_search_tool import WorkspaceSearchResult


def build_system_prompt(system_prompt: str, *, proposal_mode: bool = False) -> str:
    """构造系统提示词。"""
    base_prompt = (
        "You are Vibe Coding Agent, a warm Chinese-first programming assistant inside VS Code. "
        "Be concise, practical, and educational. "
        "When code context is available, prioritize it over generic advice. "
        "Reply in Chinese unless the user clearly asks for another language."
    )

    if proposal_mode:
        proposal_rules = (
            "You are in workspace-change planning mode. "
            "You must first understand the project context, then propose a small and coherent set of file actions. "
            "Return exactly these XML sections in order: "
            "<assistant_reply>...</assistant_reply>"
            "<proposal_summary>...</proposal_summary>"
            "<actions>...</actions>. "
            "Inside <actions>, each action must use this structure: "
            "<action><kind>create_file|update_file|update_documentation</kind>"
            "<target_file>workspace-relative path</target_file>"
            "<summary>short Chinese summary</summary>"
            "<updated_content>FULL FILE CONTENT</updated_content></action>. "
            "Use create_file for new source files, update_file for existing code/config files, "
            "and update_documentation for README or docs files. "
            "If the user asks to change code and only one file is relevant, you must still return exactly one update_file action for that file. "
            "Do not claim that changes are already embedded in the original file unless <actions></actions> is intentionally empty because no file should change. "
            "Choose the smallest reasonable set of actions. "
            "Do not output diffs. Always output full file contents for each changed file. "
            "Do not output malformed tags such as (actions>. "
            "If you cannot produce a safe change plan, return an empty <actions></actions> block and explain why."
        )
        base_prompt = f"{base_prompt}\n\n{proposal_rules}"

    if system_prompt.strip():
        return f"{base_prompt}\n\nAdditional instruction:\n{system_prompt.strip()}"

    return base_prompt


def build_user_prompt(prompt: str, context: AgentContextModel, current_notes: str) -> str:
    """构造普通问答模式的用户提示词。"""
    selected = context.selectedText.strip() if context.selectedText else "(none)"
    workspace_root = context.workspaceRoot or "(none)"
    active_file = context.activeFile or "(none)"
    language_id = context.languageId or "(unknown)"
    document = (context.documentText or "").strip()

    if len(document) > 3000:
        document = document[:3000] + "\n...[truncated]"

    return (
        "User request:\n"
        f"{prompt.strip()}\n\n"
        "Editor context:\n"
        f"- Workspace root: {workspace_root}\n"
        f"- Active file: {active_file}\n"
        f"- Language id: {language_id}\n"
        f"- Selected text:\n{selected}\n\n"
        f"- Document excerpt:\n{document if document else '(empty)'}\n\n"
        "Current-file analysis:\n"
        f"{current_notes}\n\n"
        "Response goals:\n"
        "1. Understand the request.\n"
        "2. Use the current code context when available.\n"
        "3. Give implementation-oriented advice.\n"
        "4. Explain concrete risks and next refactor steps when useful.\n"
        "5. Reply in Chinese unless the user clearly asks for another language."
    )


def build_workspace_action_prompt(
    prompt: str,
    context: AgentContextModel,
    current_notes: str,
    workspace_result: WorkspaceSearchResult,
) -> str:
    """构造项目级变更规划模式的用户提示词。"""
    selected = context.selectedText.strip() if context.selectedText else "(none)"
    workspace_root = context.workspaceRoot or "(none)"
    active_file = context.activeFile or "(none)"
    language_id = context.languageId or "(unknown)"
    active_full_text = (context.fullDocumentText or "").strip()

    if not active_full_text:
        active_full_text = "(missing full document text)"

    return (
        "User request:\n"
        f"{prompt.strip()}\n\n"
        "Active editor context:\n"
        f"- Workspace root: {workspace_root}\n"
        f"- Active file: {active_file}\n"
        f"- Language id: {language_id}\n"
        f"- Selected text:\n{selected}\n\n"
        "Current active file analysis:\n"
        f"{current_notes}\n\n"
        "Current active file full content:\n"
        "<active_file>\n"
        f"{active_full_text}\n"
        "</active_file>\n\n"
        "Relevant workspace files:\n"
        f"{workspace_result.to_prompt_text()}\n\n"
        "Planning rules:\n"
        "1. First decide which files really need to change.\n"
        "2. Prefer at most 4 actions in one plan.\n"
        "3. Source code updates should use update_file.\n"
        "4. README.md or docs/*.md changes should use update_documentation.\n"
        "5. New helper modules or new docs files should use create_file or update_documentation.\n"
        "6. Use workspace-relative paths in <target_file>.\n"
        "7. Avoid unrelated edits.\n"
        "8. Keep the result easy for beginners to read, and add concise Chinese comments only where they truly help.\n"
        "9. If only the active file needs to change, still return one update_file action for the active file.\n"
        "10. Do not say the file has already been changed unless you also provide the updated_content for that file."
    )


def build_workspace_action_repair_prompt(
    prompt: str,
    context: AgentContextModel,
    current_notes: str,
    workspace_result: WorkspaceSearchResult,
    previous_output: str,
) -> str:
    """当第一轮结构化输出失败时，要求模型重新按严格格式回答。"""
    base_prompt = build_workspace_action_prompt(prompt, context, current_notes, workspace_result)
    return (
        f"{base_prompt}\n\n"
        "Previous invalid answer:\n"
        "<previous_output>\n"
        f"{previous_output.strip()}\n"
        "</previous_output>\n\n"
        "Repair task:\n"
        "1. The previous answer did not provide valid executable XML actions.\n"
        "2. Re-answer the same task and return ONLY valid XML blocks.\n"
        "3. If only one file needs to change, return one update_file action.\n"
        "4. If no file should change, keep <actions></actions> empty and explain clearly in <assistant_reply>.\n"
        "5. Do not repeat the previous malformed format."
    )
