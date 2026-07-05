from backend.models import AgentContextModel
from backend.ml.attention_memory import AttentionMemoryResult, AttentionMemoryTool
from backend.structured_response import ParsedAction
from backend.tools.action_risk_tool import ActionRiskSummary, ActionRiskTool
from backend.tools.current_file_tool import CurrentFileTool
from backend.tools.demo_action_tool import DemoActionTool
from backend.tools.test_plan_tool import TestPlanResult, TestPlanTool
from backend.tools.workspace_action_tool import WorkspaceActionPreparationResult, WorkspaceActionTool
from backend.tools.workspace_plan_tool import WorkspacePlanResult, WorkspacePlanTool
from backend.tools.workspace_search_tool import WorkspaceSearchResult, WorkspaceSearchTool
from backend.tools.workspace_semantic_tool import WorkspaceSemanticResult, WorkspaceSemanticTool

# 文件说明：
# 本文件提供一个轻量级工作流编排层。
# 其职责不是实现细节，而是把“当前文件分析、工作区检索、动作规划、风险评估、测试计划”
# 串联起来，供 service 层统一调用。


class AgentWorkflow:
    """
    统一封装后端各个工具之间的调用顺序。
    """

    def __init__(self) -> None:
        self.current_file_tool = CurrentFileTool()
        self.workspace_search_tool = WorkspaceSearchTool()
        self.workspace_semantic_tool = WorkspaceSemanticTool()
        self.attention_memory_tool = AttentionMemoryTool()
        self.workspace_action_tool = WorkspaceActionTool()
        self.action_risk_tool = ActionRiskTool()
        self.workspace_plan_tool = WorkspacePlanTool()
        self.test_plan_tool = TestPlanTool()
        self.demo_action_tool = DemoActionTool()

    def inspect_current_context(self, context: AgentContextModel) -> str:
        """
        对当前活动文件做结构分析，并返回适合放入提示词的文本。
        """

        report = self.current_file_tool.inspect(context)
        return report.to_prompt_text()

    def inspect_workspace(self, context: AgentContextModel, prompt: str) -> WorkspaceSearchResult:
        """
        根据用户请求从工作区中检索更相关的候选文件。
        """

        return self.workspace_search_tool.search(context, prompt)

    def inspect_workspace_semantics(
        self,
        context: AgentContextModel,
        prompt: str,
        search_result: WorkspaceSearchResult,
    ) -> WorkspaceSemanticResult:
        """
        基于工作区候选文件执行轻量语义排序。
        """

        return self.workspace_semantic_tool.rank(context, prompt, search_result)

    def select_attention_context(
        self,
        context: AgentContextModel,
        prompt: str,
        search_result: WorkspaceSearchResult | None = None,
        semantic_result: WorkspaceSemanticResult | None = None,
        conversation_history=None,
        memory_items=None,
    ) -> AttentionMemoryResult:
        """
        Use simplified multi-head attention to rerank conversation, memory, and project context.
        """

        return self.attention_memory_tool.select(
            context=context,
            prompt=prompt,
            search_result=search_result,
            semantic_result=semantic_result,
            conversation_history=conversation_history or [],
            memory_items=memory_items or [],
        )

    def prepare_workspace_actions(
        self,
        context: AgentContextModel,
        parsed_actions: list[ParsedAction],
        search_result: WorkspaceSearchResult,
    ) -> WorkspaceActionPreparationResult:
        """
        对模型返回的结构化动作做路径、安全性和内容完整性校验。
        """

        return self.workspace_action_tool.prepare_actions(context, parsed_actions, search_result)

    def plan_workspace_actions(
        self,
        context: AgentContextModel,
        prompt: str,
        search_result: WorkspaceSearchResult,
    ) -> WorkspacePlanResult:
        """
        当模型没有稳定返回动作时，先用规则化方式挑出更可能需要修改的文件。
        """

        return self.workspace_plan_tool.plan(context, prompt, search_result)

    def build_test_plan(
        self,
        context: AgentContextModel,
        preparation: WorkspaceActionPreparationResult,
    ) -> TestPlanResult:
        """
        根据当前工作区与待执行动作推断测试和验证命令。
        """

        return self.test_plan_tool.build(context, preparation.actions)

    def assess_action_risk(
        self,
        context: AgentContextModel,
        preparation: WorkspaceActionPreparationResult,
        test_plan: TestPlanResult | None = None,
    ) -> ActionRiskSummary:
        """
        对已经准备好的文件动作做风险评分。
        """

        return self.action_risk_tool.assess(preparation.actions, context, test_plan)

    def build_demo_actions(self, context: AgentContextModel) -> list[ParsedAction]:
        """
        为演示示例文件生成本地保底动作，避免弱模型导致演示链路中断。
        """

        return self.demo_action_tool.build_demo_actions(context)
