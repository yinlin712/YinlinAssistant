# 文件说明：
# 本文件负责根据用户输入的大意判断请求类型。
# 当前主要区分三类：
# 1. 普通问答或分析
# 2. 当前文件直接改写
# 3. 项目级或多文件修改


def should_propose_workspace_changes(
    prompt: str,
    selected_text: str = "",
    conversation_history_text: str = "",
) -> bool:
    """
    判断当前请求是否应进入“项目级修改规划”模式。
    """

    normalized = prompt.strip().lower()
    if not normalized:
        return False

    strong_keywords = [
        "修改项目",
        "更新项目",
        "优化项目",
        "优化工程",
        "整个工程",
        "整个项目",
        "实现这个功能",
        "直接修改",
        "应用修改",
        "生成变更",
        "待确认的项目级修改方案",
        "新增文件",
        "创建文件",
        "创建一个新文件",
        "更新文档",
        "修改文档",
        "更新readme",
        "修改readme",
        "更新说明",
        "重构项目",
        "修改这个项目",
        "create a new file",
        "update the project",
        "modify the project",
        "optimize the project",
        "update readme",
        "update documentation",
        "create file",
        "apply changes",
    ]

    if any(keyword in normalized for keyword in strong_keywords):
        return True

    action_verbs = [
        "修改",
        "更新",
        "新增",
        "创建",
        "重构",
        "实现",
        "补充",
        "修复",
        "改造",
        "优化",
        "编写",
        "change",
        "update",
        "create",
        "add",
        "implement",
        "rewrite",
        "refactor",
        "fix",
        "optimize",
    ]

    project_targets = [
        "项目",
        "文件",
        "文档",
        "工程",
        "目录",
        "模块",
        "readme",
        "说明",
        "代码",
        "功能",
        "project",
        "workspace",
        "codebase",
        "module",
        "directory",
        "file",
        "documentation",
        "docs",
    ]

    has_action_verb = any(keyword in normalized for keyword in action_verbs)
    has_target = any(keyword in normalized for keyword in project_targets)
    has_contextual_project_signal = bool(conversation_history_text.strip()) and any(
        keyword in conversation_history_text.lower()
        for keyword in [
            "项目",
            "工作区",
            "多文件",
            "readme",
            "docs",
            "文档",
            "project",
            "workspace",
            "codebase",
        ]
    )
    return has_action_verb and (has_target or has_contextual_project_signal) and not selected_text.strip()


def should_directly_edit_current_file(
    prompt: str,
    selected_text: str = "",
    conversation_history_text: str = "",
) -> bool:
    """
    判断当前请求是否更适合进入“当前文件直接改写”模式。
    """

    normalized = prompt.strip().lower()
    if not normalized:
        return False

    action_verbs = [
        "修改",
        "改写",
        "重构",
        "优化",
        "修复",
        "调整",
        "补全",
        "完善",
        "改成",
        "替换",
        "封装",
        "抽取",
        "拆分",
        "整理",
        "继续",
        "edit",
        "modify",
        "rewrite",
        "refactor",
        "improve",
        "fix",
        "update",
    ]

    direct_targets = [
        "当前文件",
        "这个文件",
        "本文件",
        "当前代码",
        "这段代码",
        "选中代码",
        "选中的代码",
        "当前函数",
        "这个函数",
        "该函数",
        "当前方法",
        "这个方法",
        "该方法",
        "这个类",
        "该类",
        "current file",
        "this file",
        "current code",
        "selected code",
        "current function",
        "current method",
        "current class",
    ]

    workspace_markers = [
        "整个项目",
        "项目级",
        "工作区",
        "多文件",
        "多个文件",
        "readme",
        "docs",
        "文档",
        "project",
        "workspace",
        "codebase",
        "multiple files",
    ]

    request_markers = [
        "帮我",
        "请帮我",
        "请直接",
        "直接",
        "开始",
        "把",
        "将",
        "替我",
        "帮忙",
        "please",
    ]

    inquiry_markers = [
        "我想知道",
        "想知道",
        "解释一下",
        "请解释",
        "分析一下",
        "这个函数是干什么的",
        "什么作用",
        "什么意思",
        "为什么",
        "可以继续封装吗",
        "能不能继续封装",
    ]

    has_action_verb = any(keyword in normalized for keyword in action_verbs)
    has_direct_target = any(keyword in normalized for keyword in direct_targets)
    mentions_workspace_scope = any(keyword in normalized for keyword in workspace_markers)
    has_request_marker = any(keyword in normalized for keyword in request_markers)
    has_selected_text = bool(selected_text.strip())
    has_history_signal = any(
        keyword in conversation_history_text.lower()
        for keyword in [
            "函数",
            "方法",
            "类",
            "当前文件",
            "选中代码",
            "load_students",
            "function",
            "method",
            "class",
            "current file",
            "selected code",
        ]
    )

    if mentions_workspace_scope:
        return False

    is_inquiry = any(keyword in normalized for keyword in inquiry_markers)

    if is_inquiry and not has_request_marker:
        return False

    if has_action_verb and has_direct_target and not is_inquiry:
        return True

    if has_action_verb and (has_selected_text or has_history_signal) and has_request_marker:
        return True

    continuation_markers = ["继续", "进一步", "接着", "顺手", "继续把"]
    if (
        not is_inquiry
        and any(keyword in normalized for keyword in continuation_markers)
        and (has_selected_text or has_history_signal)
    ):
        return True

    return False


def mentions_documentation(prompt: str) -> bool:
    """
    判断当前请求是否明确提到了文档更新意图。
    """

    normalized = prompt.strip().lower()
    documentation_keywords = [
        "文档",
        "说明",
        "readme",
        "论文",
        "架构",
        "docs",
        "documentation",
    ]
    return any(keyword in normalized for keyword in documentation_keywords)
