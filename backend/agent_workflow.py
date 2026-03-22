from backend.models import AgentContextModel
from backend.structured_response import ParsedAction
from backend.tools.current_file_tool import CurrentFileTool
from backend.tools.workspace_action_tool import WorkspaceActionPreparationResult, WorkspaceActionTool
from backend.tools.workspace_search_tool import WorkspaceSearchResult, WorkspaceSearchTool


class AgentWorkflow:
    """组织后端工具调用流程的轻量级编排层。"""

    def __init__(self) -> None:
        self.current_file_tool = CurrentFileTool()
        self.workspace_search_tool = WorkspaceSearchTool()
        self.workspace_action_tool = WorkspaceActionTool()

    def inspect_current_context(self, context: AgentContextModel) -> str:
        """分析当前活动文件上下文。"""
        report = self.current_file_tool.inspect(context)
        return report.to_prompt_text()

    def inspect_workspace(self, context: AgentContextModel, prompt: str) -> WorkspaceSearchResult:
        """根据用户需求，从工作区中检索相关文件。"""
        return self.workspace_search_tool.search(context, prompt)

    def prepare_workspace_actions(
        self,
        context: AgentContextModel,
        parsed_actions: list[ParsedAction],
        search_result: WorkspaceSearchResult,
    ) -> WorkspaceActionPreparationResult:
        """对模型给出的多文件动作做安全校验与补全。"""
        return self.workspace_action_tool.prepare_actions(context, parsed_actions, search_result)
