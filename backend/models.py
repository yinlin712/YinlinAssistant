from typing import Literal, Optional

from pydantic import BaseModel, Field

# 文件说明：
# 本文件集中定义后端请求、响应和结构化动作模型。
# 这些模型是前后端通信的公共契约，字段命名应尽量稳定。
Mood = Literal["idle", "thinking", "helpful"]

# 动作类型说明：
# 当前项目级动作统一聚焦三类文件操作。
AgentActionKind = Literal["create_file", "update_file", "update_documentation"]

RiskLevel = Literal["low", "medium", "high"]
TestCommandKind = Literal["test", "validation"]
ConfidenceLevel = Literal["high", "medium", "low"]
TestOverallStatus = Literal["passed", "failed", "unknown"]
VoiceBridgeStatus = Literal["listening", "transcribing", "ready", "error"]


class AgentContextModel(BaseModel):
    """
    保存插件端采集到的编辑器上下文。
    """

    workspaceRoot: Optional[str] = None
    activeFile: Optional[str] = None
    languageId: Optional[str] = None
    selectedText: Optional[str] = None
    documentText: Optional[str] = None
    fullDocumentText: Optional[str] = None
    systemPrompt: str = Field(default="")


class ConversationTurnModel(BaseModel):
    """
    表示插件端传递给后端的最近对话上下文。
    """

    role: Literal["user", "agent"]
    content: str


class GenerateRequest(BaseModel):
    """
    表示一次后端生成请求。
    """

    prompt: str
    context: AgentContextModel
    conversationHistory: list[ConversationTurnModel] = Field(default_factory=list)


class FileActionModel(BaseModel):
    """
    表示一个可由插件端落盘执行的文件动作。
    """

    kind: AgentActionKind
    targetFile: str
    originalContent: str = Field(default="")
    updatedContent: str
    summary: str = Field(default="")


class RiskOverviewModel(BaseModel):
    """
    表示面向前端展示的整体风险概览。
    """

    level: RiskLevel = "low"
    score: int = 0
    summary: str = Field(default="")
    highlights: list[str] = Field(default_factory=list)


class TestCommandModel(BaseModel):
    """
    表示一条可执行的测试或验证命令。
    """

    command: str
    purpose: str = Field(default="")
    kind: TestCommandKind = "validation"
    confidence: ConfidenceLevel = "medium"


class TestPlanModel(BaseModel):
    """
    表示修改完成后推荐执行的测试计划。
    """

    available: bool = False
    summary: str = Field(default="")
    commands: list[TestCommandModel] = Field(default_factory=list)
    machineLearningBasis: str = Field(default="")
    hasStandardTests: bool = False


class ContextSelectionMatchModel(BaseModel):
    """
    表示一个被上下文选择模块命中的候选片段。
    """

    source: str = Field(default="")
    identifier: str = Field(default="")
    title: str = Field(default="")
    chunkType: str = Field(default="")
    location: str = Field(default="")
    weight: float = 0.0
    attentionWeight: float = 0.0
    cosineSimilarity: float = 0.0
    retrievalScore: float = 0.0
    headWeights: list[float] = Field(default_factory=list)
    excerpt: str = Field(default="")


class ContextSelectionModel(BaseModel):
    """
    表示 Embedding + 多头注意力上下文选择模块的可展示诊断结果。
    """

    available: bool = False
    summary: str = Field(default="")
    embeddingProvider: str = Field(default="")
    embeddingModel: str = Field(default="")
    fallbackUsed: bool = False
    warning: str = Field(default="")
    headCount: int = 0
    semanticFiles: list[str] = Field(default_factory=list)
    matches: list[ContextSelectionMatchModel] = Field(default_factory=list)


class GenerateResponse(BaseModel):
    """
    表示后端返回给插件端的完整响应。
    """

    content: str
    mood: Mood = "helpful"
    actions: list[FileActionModel] = Field(default_factory=list)
    requiresConfirmation: bool = False
    autoApplyActions: bool = False
    proposalSummary: str = Field(default="")
    riskOverview: RiskOverviewModel = Field(default_factory=RiskOverviewModel)
    testPlan: TestPlanModel = Field(default_factory=TestPlanModel)
    contextSelection: ContextSelectionModel = Field(default_factory=ContextSelectionModel)


class TestExecutionItemModel(BaseModel):
    """
    表示插件端执行完一条测试命令后的结果。
    """

    command: str
    purpose: str = Field(default="")
    kind: TestCommandKind = "validation"
    confidence: ConfidenceLevel = "medium"
    exitCode: int = 0
    durationMs: int = 0
    stdout: str = Field(default="")
    stderr: str = Field(default="")


class TestAnalysisRequest(BaseModel):
    """
    表示一次测试结果解释请求。
    """

    prompt: str
    context: AgentContextModel
    modifiedFiles: list[str] = Field(default_factory=list)
    executions: list[TestExecutionItemModel] = Field(default_factory=list)


class TestAnalysisResponse(BaseModel):
    """
    表示测试结果分析接口的响应。
    """

    content: str
    summary: str = Field(default="")
    overallStatus: TestOverallStatus = "unknown"


class VoiceBridgeStartRequest(BaseModel):
    """
    表示一次本地语音桥接录音会话的启动请求。
    """

    baseUrl: str = Field(default="")
    apiKey: Optional[str] = None
    model: str = Field(default="whisper-1")
    language: Optional[str] = None
    sampleRate: int = Field(default=16000)
    channels: int = Field(default=1)


class VoiceBridgeStartResponse(BaseModel):
    """
    表示本地语音桥接会话启动后的响应。
    """

    sessionId: str
    status: VoiceBridgeStatus = "listening"
    message: str = Field(default="")


class VoiceBridgeTranscriptResponse(BaseModel):
    """
    表示本地录音会话在中间转写或结束时返回的识别结果。
    """

    sessionId: str
    status: VoiceBridgeStatus = "ready"
    text: str = Field(default="")
    message: str = Field(default="")
