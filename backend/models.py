from typing import Literal, Optional

from pydantic import BaseModel, Field

# Mood 用于描述当前助手的工作状态，方便前端界面做简单状态反馈。
Mood = Literal["idle", "thinking", "helpful"]

# 第一版项目级动作统一聚焦这三类：
# 1. 创建新文件
# 2. 修改已有代码文件
# 3. 更新说明文档
AgentActionKind = Literal["create_file", "update_file", "update_documentation"]


class AgentContextModel(BaseModel):
    # workspaceRoot: 当前工作区根目录。
    workspaceRoot: Optional[str] = None

    # activeFile: 当前活动编辑器对应的文件路径。
    activeFile: Optional[str] = None

    # languageId: VS Code 识别出的语言类型，例如 python、typescript。
    languageId: Optional[str] = None

    # selectedText: 用户当前选中的代码片段。
    selectedText: Optional[str] = None

    # documentText: 当前文件的摘要内容，适合普通问答和轻量分析。
    documentText: Optional[str] = None

    # fullDocumentText: 当前活动文件的完整内容。
    # 当模型需要修改活动文件时，这个字段能帮助后端理解完整上下文。
    fullDocumentText: Optional[str] = None

    # systemPrompt: 用户或系统配置的全局提示词。
    systemPrompt: str = Field(default="")


class GenerateRequest(BaseModel):
    # prompt: 用户在插件中输入的自然语言请求。
    prompt: str

    # context: VS Code 插件收集到的编辑器上下文。
    context: AgentContextModel


class FileActionModel(BaseModel):
    # kind: 动作类型。
    kind: AgentActionKind

    # targetFile: 目标文件的绝对路径。
    targetFile: str

    # originalContent: 原始文件内容。
    # 前端会用它来生成 diff 预览，并在真正落盘前做冲突校验。
    originalContent: str = Field(default="")

    # updatedContent: 模型生成的完整新文件内容。
    updatedContent: str

    # summary: 给用户展示的变更说明。
    summary: str = Field(default="")


class GenerateResponse(BaseModel):
    # content: 展示给前端的自然语言回复。
    content: str

    # mood: 助手状态。
    mood: Mood = "helpful"

    # actions: 结构化变更动作列表。
    actions: list[FileActionModel] = Field(default_factory=list)

    # requiresConfirmation: 是否需要前端先展示预览，再由用户确认应用。
    requiresConfirmation: bool = False

    # proposalSummary: 变更预览区域使用的简要摘要。
    proposalSummary: str = Field(default="")
