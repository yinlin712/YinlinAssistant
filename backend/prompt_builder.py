from backend.models import AgentContextModel, ConversationTurnModel
from backend.tools.workspace_plan_tool import PlannedWorkspaceAction
from backend.tools.workspace_search_tool import WorkspaceSearchResult

# 文件说明：
# 本文件统一负责提示词构造。
# 不同模式的提示词应在这里集中维护，避免业务逻辑与提示词文本散落在多个文件中。


# 函数说明：
# 构造系统提示词，并按模式附加额外规则。
def build_system_prompt(
    system_prompt: str,
    *,
    proposal_mode: bool = False,
    single_file_mode: bool = False,
) -> str:
    base_prompt = (
        "You are Code Agent, a warm Chinese-first programming assistant inside VS Code. "
        "Be concise, practical, and educational. "
        "When code context is available, prioritize it over generic advice. "
        "Reply in Chinese unless the user clearly asks for another language."
    )

    if proposal_mode:
        proposal_rules = (
            "You are in workspace-change planning mode. "
            "You must first understand the project context, then propose a small and coherent set of file actions. "
            "Treat the workspace candidate files as primary evidence. "
            "If the user asks about the whole project, workspace, codebase, or multiple files, do not limit the plan to the active file. "
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
            "For project-wide refactors, prefer 2 to 5 related actions instead of only 1 action. "
            "Do not output diffs. Always output full file contents for each changed file. "
            "Do not output malformed tags such as (actions>. "
            "If you cannot produce a safe change plan, return an empty <actions></actions> block and explain why."
        )
        base_prompt = f"{base_prompt}\n\n{proposal_rules}"

    if single_file_mode:
        single_file_rules = (
            "You are in single-file rewrite mode. "
            "You will receive one target file and must return ONLY the full final content of that file. "
            "Do not explain your reasoning. "
            "Do not output XML, HTML, markdown fences, summaries, or placeholders. "
            "Do not omit code with phrases like 'not shown due to brevity'."
        )
        base_prompt = f"{base_prompt}\n\n{single_file_rules}"

    if system_prompt.strip():
        return f"{base_prompt}\n\nAdditional instruction:\n{system_prompt.strip()}"

    return base_prompt


# 函数说明：
# 构造普通问答模式的用户提示词。
def build_user_prompt(
    prompt: str,
    context: AgentContextModel,
    current_notes: str,
    conversation_history: list[ConversationTurnModel] | None = None,
) -> str:
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
        f"{_build_conversation_history_block(conversation_history)}"
        "Current-file analysis:\n"
        f"{current_notes}\n\n"
        "Response goals:\n"
        "1. Understand the request.\n"
        "2. Use the current code context when available.\n"
        "3. Give implementation-oriented advice.\n"
        "4. Explain concrete risks and next refactor steps when useful.\n"
        "5. Reply in Chinese unless the user clearly asks for another language."
    )


# 函数说明：
# 构造项目级动作规划模式的用户提示词。
def build_workspace_action_prompt(
    prompt: str,
    context: AgentContextModel,
    current_notes: str,
    workspace_result: WorkspaceSearchResult,
    semantic_retrieval_text: str = "",
    conversation_history: list[ConversationTurnModel] | None = None,
) -> str:
    selected = context.selectedText.strip() if context.selectedText else "(none)"
    workspace_root = context.workspaceRoot or "(none)"
    active_file = context.activeFile or "(none)"
    language_id = context.languageId or "(unknown)"
    project_scope_request = _looks_like_project_scope_request(prompt)
    active_full_text = (context.fullDocumentText or "").strip()

    if not active_full_text:
        active_full_text = "(missing full document text)"
    else:
        max_chars = 2200 if project_scope_request else 5000
        active_full_text = _truncate_text(active_full_text, max_chars)

    return (
        "User request:\n"
        f"{prompt.strip()}\n\n"
        "Workspace context:\n"
        f"- Workspace root: {workspace_root}\n"
        f"- Active file: {active_file}\n"
        f"- Language id: {language_id}\n"
        f"- Selected text:\n{selected}\n\n"
        f"{_build_conversation_history_block(conversation_history)}"
        "Relevant workspace files:\n"
        f"{workspace_result.to_prompt_text()}\n\n"
        "Semantic retrieval evidence:\n"
        f"{semantic_retrieval_text or '(none)'}\n\n"
        "Current active file analysis:\n"
        f"{current_notes}\n\n"
        "Current active file reference content:\n"
        "<active_file>\n"
        f"{active_full_text}\n"
        "</active_file>\n\n"
        "Planning rules:\n"
        "1. First decide which files really need to change.\n"
        "2. If the request is project-wide, prefer 2 to 5 related actions.\n"
        "3. Do not focus only on the active file when the request is about the project or workspace.\n"
        "4. Source code updates should use update_file.\n"
        "5. README.md or docs/*.md changes should use update_documentation.\n"
        "6. New helper modules or new docs files should use create_file or update_documentation.\n"
        "7. Use workspace-relative paths in <target_file>.\n"
        "8. Avoid unrelated edits.\n"
        "9. Keep the result easy to read, and add concise Chinese comments only where they are necessary.\n"
        "10. If only the active file needs to change, still return one update_file action for the active file.\n"
        "11. Do not say the file has already been changed unless you also provide the updated_content for that file.\n"
        "12. Prefer touching files that appear in the relevant workspace file list above."
    )


# 函数说明：
# 当第一轮项目级动作输出失败时，要求模型重新按严格格式回答。
def build_workspace_action_repair_prompt(
    prompt: str,
    context: AgentContextModel,
    current_notes: str,
    workspace_result: WorkspaceSearchResult,
    semantic_retrieval_text: str,
    previous_output: str,
) -> str:
    base_prompt = build_workspace_action_prompt(
        prompt,
        context,
        current_notes,
        workspace_result,
        semantic_retrieval_text,
    )
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


# 函数说明：
# 为单文件改写模式构造提示词。
def build_single_file_action_prompt(
    prompt: str,
    context: AgentContextModel,
    current_notes: str,
    workspace_result: WorkspaceSearchResult,
    planned_action: PlannedWorkspaceAction,
    original_content: str,
    conversation_history: list[ConversationTurnModel] | None = None,
) -> str:
    selected = context.selectedText.strip() if context.selectedText else "(none)"
    workspace_root = context.workspaceRoot or "(none)"
    active_file = context.activeFile or "(none)"
    language_id = context.languageId or "(unknown)"
    target_content = original_content.strip() if original_content.strip() else "(target file does not exist yet)"

    return (
        "User request:\n"
        f"{prompt.strip()}\n\n"
        "Editor context:\n"
        f"- Workspace root: {workspace_root}\n"
        f"- Active file: {active_file}\n"
        f"- Language id: {language_id}\n"
        f"- Selected text:\n{selected}\n\n"
        f"{_build_conversation_history_block(conversation_history)}"
        "Current-file analysis:\n"
        f"{current_notes}\n\n"
        "Selected target action:\n"
        f"- Kind: {planned_action.kind}\n"
        f"- Target file: {planned_action.target_file}\n"
        f"- Summary: {planned_action.summary}\n"
        f"- Rationale: {planned_action.rationale or 'Use the project context to make a safe update.'}\n\n"
        "Current target file content:\n"
        "<target_file_content>\n"
        f"{_truncate_text(target_content, 12000)}\n"
        "</target_file_content>\n\n"
        "Other relevant workspace files:\n"
        f"{_build_related_file_context(workspace_result, planned_action.target_file)}\n\n"
        "Rewrite rules:\n"
        "1. Return the full final content of the target file only.\n"
        "2. Only change the target file named above.\n"
        "3. Keep behavior consistent with the user's request and the related project context.\n"
        "4. For Python files, ensure the final code is syntactically valid.\n"
        "5. Keep comments concise and formal.\n"
        "6. Do not output summaries, XML tags, HTML tags, diff format, or markdown code fences.\n"
        "7. Do not omit code with placeholders such as TODO, omitted, brevity, 或“此处省略”。"
    )


# 函数说明：
# 为当前活动文件的直接改写模式构造提示词。
def build_current_file_edit_prompt(
    prompt: str,
    context: AgentContextModel,
    current_notes: str,
    original_content: str,
    conversation_history: list[ConversationTurnModel] | None = None,
) -> str:
    selected = context.selectedText.strip() if context.selectedText else "(none)"
    workspace_root = context.workspaceRoot or "(none)"
    active_file = context.activeFile or "(none)"
    language_id = context.languageId or "(unknown)"

    return (
        "User request:\n"
        f"{prompt.strip()}\n\n"
        "Direct-edit context:\n"
        f"- Workspace root: {workspace_root}\n"
        f"- Active file: {active_file}\n"
        f"- Language id: {language_id}\n"
        f"- Selected text:\n{selected}\n\n"
        f"{_build_conversation_history_block(conversation_history)}"
        "Current-file analysis:\n"
        f"{current_notes}\n\n"
        "Current active file full content:\n"
        "<active_file_content>\n"
        f"{_truncate_text(original_content, 14000)}\n"
        "</active_file_content>\n\n"
        "Rewrite rules:\n"
        "1. You are editing the current active file only.\n"
        "2. Return the full final content of the active file only.\n"
        "3. If selected text is provided, prioritize the requested change around that code region.\n"
        "4. Keep unrelated code unchanged unless a small supporting refactor is required.\n"
        "5. Preserve the file's main behavior while completing the requested modification.\n"
        "6. For Python files, ensure the final code is syntactically valid.\n"
        "7. Keep Chinese comments concise and formal when comments are necessary.\n"
        "8. Do not output XML, HTML, markdown fences, summaries, placeholders, or diff format.\n"
        "9. Do not claim that the file has already been changed; output the changed full file content directly."
    )


# 函数说明：
# 当当前文件直接改写结果无效时，要求模型重新只返回完整文件内容。
def build_current_file_edit_repair_prompt(
    prompt: str,
    active_file: str,
    invalid_output: str,
    validation_error: str,
) -> str:
    return (
        "The previous direct-edit answer for the active file was invalid.\n"
        f"User request:\n{prompt.strip()}\n\n"
        "Active file:\n"
        f"{active_file}\n\n"
        "Validation error:\n"
        f"{validation_error}\n\n"
        "Previous invalid output:\n"
        "<previous_output>\n"
        f"{_truncate_text(invalid_output, 6000)}\n"
        "</previous_output>\n\n"
        "Repair rules:\n"
        "1. Return ONLY the full final file content.\n"
        "2. Do not output XML, HTML, markdown fences, summaries, or explanations.\n"
        "3. Do not omit code.\n"
        "4. Keep the response focused on the current active file."
    )


# 函数说明：
# 当单文件改写结果无效时，要求模型只返回修复后的完整文件内容。
def build_single_file_repair_prompt(
    prompt: str,
    planned_action: PlannedWorkspaceAction,
    invalid_output: str,
    validation_error: str,
) -> str:
    return (
        "The previous answer for this target file was invalid.\n"
        f"User request:\n{prompt.strip()}\n\n"
        "Target file:\n"
        f"- Kind: {planned_action.kind}\n"
        f"- Target file: {planned_action.target_file}\n"
        f"- Summary: {planned_action.summary}\n\n"
        "Validation error:\n"
        f"{validation_error}\n\n"
        "Previous invalid output:\n"
        "<previous_output>\n"
        f"{_truncate_text(invalid_output, 6000)}\n"
        "</previous_output>\n\n"
        "Repair rules:\n"
        "1. Return ONLY the full final file content.\n"
        "2. Do not output XML, HTML, markdown fences, summaries, or explanations.\n"
        "3. Do not omit code.\n"
        "4. If the target file is Python, the output must be valid Python syntax."
    )


# 函数说明：
# 从工作区候选中挑出少量相关文件作为单文件改写的辅助上下文。
def _build_related_file_context(workspace_result: WorkspaceSearchResult, target_file: str) -> str:
    related_blocks: list[str] = []
    normalized_target = target_file.replace("\\", "/").lower()

    for snapshot in workspace_result.candidate_files:
        relative_path = snapshot.relative_path.replace("\\", "/")
        if relative_path.lower() == normalized_target:
            continue

        related_blocks.append(
            f"<related_file path=\"{relative_path}\" reason=\"{snapshot.reason}\">\n"
            f"{_truncate_text(snapshot.excerpt, 1800)}\n"
            "</related_file>"
        )

        if len(related_blocks) >= 3:
            break

    return "\n".join(related_blocks) if related_blocks else "(none)"


# 函数说明：
# 判断当前请求是否更接近项目级或多文件范围，用于控制提示词的侧重点。
def _looks_like_project_scope_request(prompt: str) -> bool:
    normalized = prompt.strip().lower()
    keywords = [
        "整个项目",
        "项目级",
        "工程级",
        "工作区",
        "多文件",
        "多个文件",
        "项目代码",
        "codebase",
        "workspace",
        "project",
        "multiple files",
        "across files",
    ]
    return any(keyword in normalized for keyword in keywords)


# 函数说明：
# 将较长文本截断到提示词可接受的长度。
def _truncate_text(content: str, max_chars: int) -> str:
    if len(content) <= max_chars:
        return content
    return content[:max_chars] + "\n...[truncated]"


# 函数说明：
# 将最近对话整理为提示词片段，帮助模型理解连续对话意图。
def _build_conversation_history_block(
    conversation_history: list[ConversationTurnModel] | None,
) -> str:
    if not conversation_history:
        return ""

    lines = ["Recent conversation:"]
    for turn in conversation_history[-6:]:
        speaker = "User" if turn.role == "user" else "Assistant"
        lines.append(f"- {speaker}: {turn.content.strip()}")

    return "\n".join(lines) + "\n\n"
