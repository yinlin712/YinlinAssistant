from typing import Literal, Optional

from pydantic import BaseModel, Field

# 文件说明：
# 本文件集中定义后端请求、响应和结构化动作模型。
# 这些模型是前后端通信的公共契约，字段命名应尽量稳定。

# 状态说明：
# 用于描述助手当前所处的工作状态，便于前端显示简单状态提示。
Mood = Literal["idle", "thinking", "helpful"]

# 动作类型说明：
# 当前项目级动作统一聚焦三类文件操作。
AgentActionKind = Literal["create_file", "update_file", "update_documentation"]


# 模型说明：
# 保存插件端采集到的编辑器上下文。
class AgentContextModel(BaseModel):
    workspaceRoot: Optional[str] = None
    activeFile: Optional[str] = None
    languageId: Optional[str] = None
    selectedText: Optional[str] = None
    documentText: Optional[str] = None
    fullDocumentText: Optional[str] = None
    systemPrompt: str = Field(default="")


# 模型说明：
# 表示插件端传递给后端的最近对话上下文。
class ConversationTurnModel(BaseModel):
    role: Literal["user", "agent"]
    content: str


# 模型说明：
# 表示一次后端生成请求。
class GenerateRequest(BaseModel):
    prompt: str
    context: AgentContextModel
    conversationHistory: list[ConversationTurnModel] = Field(default_factory=list)


# 模型说明：
# 表示一个可由插件端落盘执行的文件动作。
class FileActionModel(BaseModel):
    kind: AgentActionKind
    targetFile: str
    originalContent: str = Field(default="")
    updatedContent: str
    summary: str = Field(default="")


# 模型说明：
# 表示后端返回给插件端的完整响应。
class GenerateResponse(BaseModel):
    content: str
    mood: Mood = "helpful"
    actions: list[FileActionModel] = Field(default_factory=list)
    requiresConfirmation: bool = False
    autoApplyActions: bool = False
    proposalSummary: str = Field(default="")
