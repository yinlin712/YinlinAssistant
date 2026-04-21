from backend.models import AgentContextModel
from backend.structured_response import ParsedAction
from backend.tools.action_risk_tool import ActionRiskSummary, ActionRiskTool
from backend.tools.current_file_tool import CurrentFileTool
from backend.tools.demo_action_tool import DemoActionTool
from backend.tools.workspace_action_tool import WorkspaceActionPreparationResult, WorkspaceActionTool
from backend.tools.workspace_plan_tool import WorkspacePlanResult, WorkspacePlanTool
from backend.tools.workspace_semantic_tool import WorkspaceSemanticResult, WorkspaceSemanticTool
from backend.tools.workspace_search_tool import WorkspaceSearchResult, WorkspaceSearchTool

# 文件说明：
# 本文件提供一个轻量级工作流编排层。
# 其职责不是实现细节，而是把“当前文件分析、工作区检索、动作规划、动作校验”串起来。


# 类说明：
# 统一封装后端各个工具之间的调用顺序。
class AgentWorkflow:
    # 方法说明：
    # 初始化所有工作流阶段用到的工具对象。
    def __init__(self) -> None:
        self.current_file_tool = CurrentFileTool()
        self.workspace_search_tool = WorkspaceSearchTool()
        self.workspace_semantic_tool = WorkspaceSemanticTool()
        self.workspace_action_tool = WorkspaceActionTool()
        self.action_risk_tool = ActionRiskTool()
        self.workspace_plan_tool = WorkspacePlanTool()
        self.demo_action_tool = DemoActionTool()

    # 方法说明：
    # 对当前活动文件做结构分析，并返回适合放入提示词的文本。
    def inspect_current_context(self, context: AgentContextModel) -> str:
        report = self.current_file_tool.inspect(context)
        return report.to_prompt_text()

    # 方法说明：
    # 根据用户请求从工作区中检索更相关的候选文件。
    def inspect_workspace(self, context: AgentContextModel, prompt: str) -> WorkspaceSearchResult:
        return self.workspace_search_tool.search(context, prompt)

    # 方法说明：
    # 基于工作区候选文件执行轻量语义排序，为后续 Prompt 组装和演示说明提供依据。
    def inspect_workspace_semantics(
        self,
        context: AgentContextModel,
        prompt: str,
        search_result: WorkspaceSearchResult,
    ) -> WorkspaceSemanticResult:
        return self.workspace_semantic_tool.rank(context, prompt, search_result)

    # 方法说明：
    # 对模型返回的结构化动作做路径、安全性和内容完整性校验。
    def prepare_workspace_actions(
        self,
        context: AgentContextModel,
        parsed_actions: list[ParsedAction],
        search_result: WorkspaceSearchResult,
    ) -> WorkspaceActionPreparationResult:
        return self.workspace_action_tool.prepare_actions(context, parsed_actions, search_result)

    # 方法说明：
    # 当模型没有稳定返回动作时，先用规则化方式挑出更可能需要修改的文件。
    def plan_workspace_actions(
        self,
        context: AgentContextModel,
        prompt: str,
        search_result: WorkspaceSearchResult,
    ) -> WorkspacePlanResult:
        return self.workspace_plan_tool.plan(context, prompt, search_result)

    # 方法说明：
    # 对已经准备好的文件动作做风险评分，便于前端展示整体风险与单文件风险提示。
    def assess_action_risk(
        self,
        context: AgentContextModel,
        preparation: WorkspaceActionPreparationResult,
    ) -> ActionRiskSummary:
        return self.action_risk_tool.assess(preparation.actions, context)

    # 方法说明：
    # 为演示示例文件生成本地保底动作，避免弱模型导致演示链路中断。
    def build_demo_actions(self, context: AgentContextModel) -> list[ParsedAction]:
        return self.demo_action_tool.build_demo_actions(context)
