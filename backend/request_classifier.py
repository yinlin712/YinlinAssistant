# 文件说明：
# 本文件负责根据用户输入的大意判断请求类型。
# 当前主要区分两类：
# 1. 普通问答或分析
# 2. 涉及真实文件修改的项目级请求


# 函数说明：
# 判断当前请求是否应进入“项目级修改规划”模式。
def should_propose_workspace_changes(prompt: str) -> bool:
    normalized = prompt.strip().lower()
    if not normalized:
        return False

    strong_keywords = [
        "修改项目",
        "更新项目",
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
        "修改当前文件",
        "修改这个项目",
        "create a new file",
        "update the project",
        "modify the project",
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
    ]

    project_targets = [
        "项目",
        "文件",
        "文档",
        "readme",
        "说明",
        "代码",
        "功能",
        "project",
        "file",
        "documentation",
        "docs",
        "codebase",
    ]

    has_action_verb = any(keyword in normalized for keyword in action_verbs)
    has_target = any(keyword in normalized for keyword in project_targets)
    return has_action_verb and has_target


# 函数说明：
# 判断当前请求是否明确提到了文档更新意图。
def mentions_documentation(prompt: str) -> bool:
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
