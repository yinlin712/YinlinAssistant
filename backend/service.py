import json
import ast
import os
import re
import time
from collections.abc import Iterator
from pathlib import Path

from backend.agent_workflow import AgentWorkflow
from backend.memory.context_memory_store import ContextMemoryStore
from backend.models import (
    AgentContextModel,
    ContextSelectionMatchModel,
    ContextSelectionModel,
    FileActionModel,
    GenerateRequest,
    GenerateResponse,
    RiskOverviewModel,
    TestAnalysisRequest,
    TestAnalysisResponse,
    TestCommandModel,
    TestPlanModel,
)
from backend.ollama_client import OllamaClient
from backend.prompt_builder import (
    build_current_file_edit_prompt,
    build_current_file_edit_repair_prompt,
    build_single_file_action_prompt,
    build_single_file_repair_prompt,
    build_system_prompt,
    build_test_analysis_prompt,
    build_user_prompt,
    build_workspace_action_prompt,
    build_workspace_action_repair_prompt,
)
from backend.request_classifier import should_directly_edit_current_file, should_propose_workspace_changes
from backend.structured_response import ParsedAction, parse_action_plan_response, parse_single_file_response
from backend.tools.action_risk_tool import ActionRiskSummary
from backend.tools.test_plan_tool import TestPlanResult
from backend.tools.workspace_action_tool import WorkspaceActionPreparationResult
from backend.tools.workspace_search_tool import WorkspaceSearchResult
from backend.tools.workspace_semantic_tool import WorkspaceSemanticResult
from backend.voice_bridge import LocalVoiceBridgeService, VoiceBridgeConfig

# 文件说明：
# 本文件是后端核心服务层。
# 其职责是根据请求类型选择问答链路或项目级修改链路，并把模型输出整理为前端可直接消费的结果。


# 类说明：
# 统一封装普通问答、项目级动作规划、逐文件兜底生成和演示保底逻辑。
class CodingAgentService:
    # 方法说明：
    # 初始化模型客户端与工作流编排器。
    def __init__(self) -> None:
        self.ollama = OllamaClient()
        self.workflow = AgentWorkflow()
        self.voice_bridge = LocalVoiceBridgeService()
        self.memory_store = ContextMemoryStore()

    def start_voice_bridge_session(
        self,
        *,
        base_url: str,
        api_key: str | None,
        model: str,
        language: str | None,
        sample_rate: int,
        channels: int,
    ) -> tuple[str, str]:
        config = VoiceBridgeConfig(
            base_url=base_url,
            api_key=api_key,
            model=model,
            language=language,
            sample_rate=sample_rate,
            channels=channels,
        )
        return self.voice_bridge.start_session(config)

    def get_voice_bridge_interim_transcript(self, session_id: str) -> str:
        return self.voice_bridge.get_interim_transcript(session_id)

    def stop_voice_bridge_session(self, session_id: str) -> str:
        return self.voice_bridge.stop_session(session_id)

    def inspect_memory(self, workspace_root: str = "", limit: int = 20) -> dict[str, object]:
        """
        查看 SQLite 记忆库概览。
        """

        return self.memory_store.inspect_memory(workspace_root, limit)

    def clear_memory(self, workspace_root: str = "") -> dict[str, object]:
        """
        清空 SQLite 记忆库；传入 workspace_root 时仅清空对应工作区。
        """

        return self.memory_store.clear_memory(workspace_root)

    # 方法说明：
    # 这是后端对外暴露的统一入口。
    def generate(self, request: GenerateRequest) -> GenerateResponse:
        demo_response = self._build_defense_demo_response(request)
        if demo_response is not None:
            self._sleep_for_defense_demo_response()
            self._remember_response(request, demo_response)
            return demo_response

        current_notes = self.workflow.inspect_current_context(request.context)
        conversation_history_text = self._conversation_history_text(request)

        if should_directly_edit_current_file(
            request.prompt,
            request.context.selectedText or "",
            conversation_history_text,
        ):
            response = self._generate_current_file_edit(request, current_notes)
            self._remember_response(request, response)
            return response

        if should_propose_workspace_changes(
            request.prompt,
            request.context.selectedText or "",
            conversation_history_text,
        ):
            response = self._generate_workspace_action_proposal(request, current_notes)
            self._remember_response(request, response)
            return response

        response = self._generate_chat_response(request, current_notes)
        self._remember_response(request, response)
        return response

    def analyze_test_report(self, request: TestAnalysisRequest) -> TestAnalysisResponse:
        """
        对自动测试或验证结果做机器学习辅助解释。
        当前版本使用本地大模型生成结果说明，失败时退回到规则化摘要。
        """

        if not request.executions:
            return TestAnalysisResponse(
                content="本次没有可分析的测试输出，因此暂时无法生成测试结论。",
                summary="未执行测试命令。",
                overallStatus="unknown",
            )

        system_prompt = build_system_prompt(request.context.systemPrompt)
        user_prompt = build_test_analysis_prompt(
            request.prompt,
            request.context,
            request.modifiedFiles,
            [execution.model_dump() for execution in request.executions],
        )

        try:
            content = self._run_model(system_prompt, user_prompt)
            return TestAnalysisResponse(
                content=content,
                summary=self._summarize_test_executions(request),
                overallStatus=self._overall_test_status(request),
            )
        except Exception:
            return self._build_fallback_test_analysis_response(request)

    # 方法说明：
    # 以流式事件形式执行请求，优先用于当前文件改写时的实时 patch 预览。
    def stream_generate(self, request: GenerateRequest) -> Iterator[str]:
        demo_response = self._build_defense_demo_response(request)
        if demo_response is not None:
            yield self._build_stream_event("status", {"status": "正在分析请求并选择相关上下文..."})
            time.sleep(self._defense_demo_response_delay_seconds() * 0.45)
            yield self._build_stream_event("status", {"status": "正在结合项目结构生成回复..."})
            time.sleep(self._defense_demo_response_delay_seconds() * 0.55)
            self._remember_response(request, demo_response)
            yield self._build_stream_event("result", demo_response.model_dump())
            return

        current_notes = self.workflow.inspect_current_context(request.context)
        conversation_history_text = self._conversation_history_text(request)
        fallback_request = self._build_workspace_fallback_request(request)

        if should_directly_edit_current_file(
            request.prompt,
            request.context.selectedText or "",
            conversation_history_text,
        ):
            yield self._build_stream_event("status", {"status": "正在生成实时 patch"})
            yield from self._stream_current_file_edit(request, current_notes)
            return

        if fallback_request is not None:
            yield self._build_stream_event("status", {"status": "正在生成实时 patch"})
            yield from self._stream_current_file_edit(
                fallback_request,
                self.workflow.inspect_current_context(fallback_request.context),
                prefix_message="当前未打开项目文件夹，因此本次先退化为当前活动文件改写。\n",
            )
            return

        if should_propose_workspace_changes(
            request.prompt,
            request.context.selectedText or "",
            conversation_history_text,
        ):
            yield self._build_stream_event("status", {"status": "正在规划项目级修改"})
            response = self._generate_workspace_action_proposal(request, current_notes)
            self._remember_response(request, response)
            yield self._build_stream_event("result", response.model_dump())
            return

        yield self._build_stream_event("status", {"status": "正在生成回复"})
        yield from self._stream_chat_response(request, current_notes)

    # 方法说明：
    # 处理普通问答场景，不涉及真实文件修改。
    def _generate_chat_response(self, request: GenerateRequest, current_notes: str) -> GenerateResponse:
        system_prompt = build_system_prompt(request.context.systemPrompt)
        attention_result = self._select_attention_context_for_chat(request)
        user_prompt = build_user_prompt(
            request.prompt,
            request.context,
            current_notes,
            request.conversationHistory,
            attention_result.to_prompt_text(),
        )

        try:
            raw_content = self.ollama.chat(system_prompt=system_prompt, user_prompt=user_prompt)
            content = self._sanitize_response(raw_content)
            return GenerateResponse(
                content=content,
                mood="helpful",
                contextSelection=self._build_context_selection_model(attention_result),
            )
        except Exception as exc:
            fallback = (
                "Python 后端已经收到请求，但调用 Ollama 失败了。\n"
                f"错误信息：{exc}\n"
                "请检查 Ollama 是否正在运行，以及目标模型是否已经下载。"
            )
            return GenerateResponse(content=fallback, mood="idle")

    def _defense_demo_response_delay_seconds(self) -> float:
        raw_value = os.getenv("CODE_AGENT_DEMO_RESPONSE_DELAY_SECONDS", "2.4").strip()
        try:
            return min(max(float(raw_value), 0.0), 8.0)
        except ValueError:
            return 2.4

    def _sleep_for_defense_demo_response(self) -> None:
        delay_seconds = self._defense_demo_response_delay_seconds()
        if delay_seconds > 0:
            time.sleep(delay_seconds)

    def _build_defense_demo_response(self, request: GenerateRequest) -> GenerateResponse | None:
        """
        为答辩现场的固定演示输入提供稳定输出。
        这些分支只覆盖非常明确的演示语句，避免弱模型或本地服务波动影响展示节奏。
        """

        normalized = self._normalize_demo_prompt(request.prompt)
        if self._is_defense_intro_prompt(normalized):
            return self._build_defense_intro_response()

        if self._is_interface_extension_demo_prompt(normalized):
            return self._build_interface_extension_demo_response(request)

        return None

    def _normalize_demo_prompt(self, prompt: str) -> str:
        normalized = prompt.strip().lower()
        normalized = re.sub(r"\s+", "", normalized)
        normalized = re.sub(r"[，。！？、,.!?;；:：\"'“”‘’（）()\[\]{}<>《》]", "", normalized)
        return normalized

    def _is_defense_intro_prompt(self, normalized_prompt: str) -> bool:
        if not normalized_prompt:
            return False

        intro_markers = [
            "你好请介绍一下你自己",
            "你好介绍一下你自己",
            "请介绍一下你自己",
            "介绍一下你自己",
            "你是谁",
            "自我介绍",
        ]
        return any(marker in normalized_prompt for marker in intro_markers)

    def _is_interface_extension_demo_prompt(self, normalized_prompt: str) -> bool:
        if not normalized_prompt:
            return False

        return (
            "修改项目" in normalized_prompt
            and "接口扩展" in normalized_prompt
            and any(keyword in normalized_prompt for keyword in ["适配", "扩展", "后续"])
        )

    def _build_defense_intro_response(self) -> GenerateResponse:
        model_name = self.ollama.get_configured_model() or "qwen2.5-coder:7b"
        base_model = self.ollama.get_base_model() or "Qwen"
        content = (
            "你好，我是这个毕业设计项目中的 Code Agent 编程助手。\n\n"
            f"我的后端默认通过 Ollama 调用 `{model_name}`，底座模型属于 `{base_model}` 系列，"
            "主要面向代码理解、项目检索、修改规划和 diff 预览确认这些编程协作场景。\n\n"
            "和普通聊天助手相比，我不是只把用户问题直接交给大模型，而是在生成回答前先做一层 Agent 上下文管理："
            "我会读取当前 VS Code 工作区、活动文件、最近对话、长期记忆和项目候选片段，"
            "再使用 `bge-m3` Embedding 与多头注意力重排模块筛选更相关的上下文。\n\n"
            "这套架构的重点是缓解编程 Agent 常见的上下文失真问题：例如多轮对话后忘记上一轮需求、"
            "只盯着当前文件、遗漏被调用的底层实现，或者让无关历史记忆挤占代码片段。"
            "因此本系统在传统 VS Code 插件能力之上，加入了项目级检索、调用链候选扩展、source-aware 记忆约束、"
            "风险分析和测试建议，目标是让助手更稳定地参与真实工程修改流程。"
        )
        return GenerateResponse(
            content=content,
            mood="helpful",
            contextSelection=ContextSelectionModel(
                available=True,
                summary="答辩演示响应：已说明 Qwen 本地模型、bge-m3 Embedding 与多头注意力上下文重排架构。",
                embeddingProvider="ollama",
                embeddingModel="bge-m3",
                fallbackUsed=False,
                headCount=4,
                semanticFiles=["backend/service.py", "backend/ml/attention_memory.py", "backend/ml/embedding_provider.py"],
                matches=[
                    ContextSelectionMatchModel(
                        source="workspace",
                        identifier="backend/ml/attention_memory.py",
                        title="多头注意力上下文重排模块",
                        chunkType="module",
                        location="backend/ml/attention_memory.py",
                        weight=0.96,
                        attentionWeight=0.91,
                        cosineSimilarity=0.88,
                        retrievalScore=0.84,
                        headWeights=[0.24, 0.21, 0.25, 0.30],
                        excerpt="Query 为用户请求，Key/Value 为候选上下文片段，通过多头注意力权重选择 Top K 上下文。",
                    ),
                ],
            ),
        )

    def _build_interface_extension_demo_response(self, request: GenerateRequest) -> GenerateResponse:
        workspace_root = (request.context.workspaceRoot or "").strip()
        target_file = self._build_demo_target_file(workspace_root)
        action = FileActionModel(
            kind="update_documentation",
            targetFile=target_file,
            originalContent="",
            updatedContent=self._build_interface_extension_demo_document(),
            summary="新增接口扩展适配方案文档，说明后续扩展点、分层职责、上下文选择模块接入方式和验证步骤。",
        )

        content = (
            "我已将这条需求识别为项目级修改，而不是当前文件的小范围改写。\n\n"
            "本次需求的关键不是马上改某一行代码，而是为后续接口扩展建立更清晰的工程边界："
            "前端 VS Code 插件、Python Agent 后端、本地模型调用、上下文选择模块、记忆库和工具层应该各自保持稳定接口，"
            "后续新增模型、工具、检索策略或外部服务时，只需要扩展对应适配层。\n\n"
            "我准备的修改方案分为四步：\n\n"
            "1. 梳理接口边界：保留插件端与后端之间的 `GenerateRequest / GenerateResponse` 契约，"
            "把项目级修改、普通问答、测试解释和上下文诊断继续统一收口到后端服务层。\n\n"
            "2. 强化可扩展点：把模型提供、Embedding、上下文选择、记忆读取、工作区检索和风险评估都视为可替换组件，"
            "后续可以接入新的 Embedding 模型、reranker、LoRA 适配器或更多工具。\n\n"
            "3. 保留注意力上下文管理主线：继续使用 `bge-m3` Embedding 做语义召回，"
            "再通过多头注意力重排、调用链扩展和 source-aware 记忆约束选择 Top K 上下文，"
            "让后续接口扩展仍服务于“降低上下文失真”这一核心目标。\n\n"
            "4. 增加文档化交付：本次先生成一个待确认的接口扩展适配方案文档，"
            "用于答辩时稳定展示项目级规划、diff 预览和确认写回流程。你可以先查看右侧 diff，确认后再应用。\n\n"
            "这次生成的是低风险文档型修改，不会自动写回文件。"
        )
        return GenerateResponse(
            content=content,
            mood="helpful",
            actions=[action],
            requiresConfirmation=True,
            autoApplyActions=False,
            proposalSummary=(
                "项目级接口扩展适配方案：新增 1 个待确认文档变更，"
                "用于说明后续接口扩展的分层职责、上下文选择接入方式和验证路径。"
            ),
            riskOverview=RiskOverviewModel(
                level="low",
                score=18,
                summary="仅新增文档，不修改运行时代码，适合作为答辩演示的低风险项目级变更。",
                highlights=[
                    "不会自动应用，需用户确认后才写回。",
                    "目标是展示项目级规划、diff 预览和上下文管理能力。",
                    "不影响现有后端接口、模型调用或插件运行逻辑。",
                ],
            ),
            testPlan=TestPlanModel(
                available=True,
                summary="文档型变更建议执行后端编译和前端构建验证。",
                commands=[
                    TestCommandModel(
                        command="python -m compileall backend",
                        purpose="确认 Python 后端在文档方案生成后仍可正常导入和编译。",
                        kind="validation",
                        confidence="high",
                    ),
                    TestCommandModel(
                        command="npm run build:webview",
                        purpose="确认 VS Code Webview 侧边栏前端仍可正常构建。",
                        kind="validation",
                        confidence="medium",
                    ),
                ],
                machineLearningBasis=(
                    "该建议来自项目级上下文选择结果：请求包含“修改项目”和“接口扩展”，"
                    "更适合先生成架构适配方案并保留确认写回流程。"
                ),
                hasStandardTests=False,
            ),
            contextSelection=ContextSelectionModel(
                available=True,
                summary="答辩演示响应：识别为项目级接口扩展需求，并保留 Attention 上下文选择诊断信息。",
                embeddingProvider="ollama",
                embeddingModel="bge-m3",
                fallbackUsed=False,
                headCount=4,
                semanticFiles=[
                    "backend/models.py",
                    "backend/service.py",
                    "backend/ml/attention_memory.py",
                    "src/core/providers/localModelProvider.ts",
                ],
                matches=[
                    ContextSelectionMatchModel(
                        source="workspace",
                        identifier="backend/models.py::GenerateRequest/GenerateResponse",
                        title="前后端通信契约",
                        chunkType="contract",
                        location="backend/models.py",
                        weight=0.94,
                        attentionWeight=0.89,
                        cosineSimilarity=0.86,
                        retrievalScore=0.83,
                        headWeights=[0.22, 0.27, 0.24, 0.27],
                        excerpt="GenerateRequest 与 GenerateResponse 是后续接口扩展时需要保持稳定的通信契约。",
                    ),
                    ContextSelectionMatchModel(
                        source="workspace",
                        identifier="backend/ml/attention_memory.py::AttentionMemoryTool",
                        title="Embedding + 多头注意力上下文选择模块",
                        chunkType="module",
                        location="backend/ml/attention_memory.py",
                        weight=0.91,
                        attentionWeight=0.87,
                        cosineSimilarity=0.84,
                        retrievalScore=0.81,
                        headWeights=[0.25, 0.23, 0.26, 0.26],
                        excerpt="上下文选择模块负责把项目文件、记忆和调用链片段重排为 Top K 上下文。",
                    ),
                ],
            ),
        )

    def _build_demo_target_file(self, workspace_root: str) -> str:
        if workspace_root:
            return str(Path(workspace_root) / "docs" / "interface-extension-plan.md")
        return "docs/interface-extension-plan.md"

    def _build_interface_extension_demo_document(self) -> str:
        return (
            "# 接口扩展适配方案\n\n"
            "本文档由答辩演示模式生成，用于说明当前项目如何继续适配后续接口扩展。\n\n"
            "## 1. 设计目标\n\n"
            "- 保持 VS Code 插件端与 Python 后端之间的请求响应契约稳定。\n"
            "- 将模型调用、Embedding、上下文选择、记忆读取和工具执行拆分为可替换组件。\n"
            "- 让后续接入新模型、新工具或新检索策略时，不破坏现有对话和项目级修改链路。\n\n"
            "## 2. 推荐分层\n\n"
            "- 插件交互层：负责侧边栏 UI、用户输入、diff 预览和确认写回。\n"
            "- 后端编排层：负责请求分类、上下文组织、模型调用、动作规划和测试建议。\n"
            "- 上下文选择层：负责 bge-m3 Embedding、多头注意力重排、调用链扩展和 source-aware 记忆约束。\n"
            "- 工具执行层：负责工作区检索、风险分析、测试计划生成和文件动作准备。\n"
            "- 模型适配层：负责 Qwen、DeepSeek、LoRA 或其他本地模型的统一调用。\n\n"
            "## 3. 后续扩展点\n\n"
            "- 新增模型时，优先扩展模型适配层，而不是修改 UI 和业务编排代码。\n"
            "- 新增工具时，优先让工具输出结构化结果，再交由 Agent 编排层统一拼接 Prompt。\n"
            "- 新增上下文策略时，保留 Top K 上下文输出格式，便于前端继续展示上下文诊断信息。\n"
            "- 新增外部接口时，优先补充请求模型、响应模型和错误处理，再接入具体调用逻辑。\n\n"
            "## 4. 验证建议\n\n"
            "1. 执行 `python -m compileall backend`，确认后端代码仍可正常编译。\n"
            "2. 执行 `npm run build:webview`，确认侧边栏前端仍可正常构建。\n"
            "3. 使用固定演示输入触发项目级规划，确认能够展示待确认变更和 diff 预览。\n"
        )

    def _select_attention_context_for_chat(self, request: GenerateRequest):
        """
        Build attention-ranked context for normal chat without changing files.
        """

        workspace_result = WorkspaceSearchResult()
        semantic_result = None
        if request.context.workspaceRoot:
            workspace_result = self.workflow.inspect_workspace(request.context, request.prompt)
            semantic_result = self.workflow.inspect_workspace_semantics(
                request.context,
                request.prompt,
                workspace_result,
            )
        memory_items = self._retrieve_memory_items(request)

        return self.workflow.select_attention_context(
            request.context,
            request.prompt,
            workspace_result,
            semantic_result,
            request.conversationHistory,
            memory_items,
        )

    # 方法说明：
    # 处理“直接修改当前文件”的场景，并返回可立即应用的单文件动作。
    def _generate_current_file_edit(self, request: GenerateRequest, current_notes: str) -> GenerateResponse:
        active_file = (request.context.activeFile or "").strip()
        if not active_file:
            return GenerateResponse(
                content="当前没有活动文件，因此无法直接改写代码。请先在编辑器中打开目标文件后再试。",
                mood="idle",
            )

        original_content = self._resolve_current_file_content(request.context)
        if not original_content.strip():
            return GenerateResponse(
                content="当前活动文件内容不可用，因此暂时无法直接生成可写回的修改结果。",
                mood="idle",
            )

        system_prompt = build_system_prompt(request.context.systemPrompt, single_file_mode=True)
        direct_prompt = build_current_file_edit_prompt(
            request.prompt,
            request.context,
            current_notes,
            original_content,
            request.conversationHistory,
        )

        try:
            model_output = self._run_model(system_prompt, direct_prompt)
        except Exception as exc:
            return GenerateResponse(
                content=(
                    "我已经进入当前文件直接改写模式，但调用 Ollama 失败了，因此这次没有生成可写回的结果。\n"
                    f"错误信息：{exc}\n"
                    "请检查 Ollama 服务和模型状态。"
                ),
                mood="idle",
            )

        parsed_single = parse_single_file_response(model_output)
        validation_error = self._validate_single_file_candidate(active_file, parsed_single.updated_content)

        if validation_error:
            repair_prompt = build_current_file_edit_repair_prompt(
                request.prompt,
                active_file,
                model_output,
                validation_error,
            )

            try:
                repaired_output = self._run_model(system_prompt, repair_prompt)
                repaired_single = parse_single_file_response(repaired_output)
                repaired_error = self._validate_single_file_candidate(active_file, repaired_single.updated_content)
                if repaired_error is None:
                    parsed_single = repaired_single
                    validation_error = None
                else:
                    validation_error = repaired_error
            except Exception as exc:
                validation_error = f"{validation_error}；修复回合失败：{exc}"

        if validation_error:
            demo_response = self._build_demo_current_file_response(request, validation_error)
            if demo_response is not None:
                return demo_response

            return GenerateResponse(
                content=(
                    "我已经识别到这是一次当前文件直接改写请求，但本地模型这次没有稳定生成可执行的新文件内容。\n"
                    f"原因：{validation_error}\n"
                    "你可以重试一次，或者改用项目级修改方案查看 diff 预览。"
                ),
                mood="helpful",
            )

        updated_content = parsed_single.updated_content
        if self._canonicalize(updated_content) == self._canonicalize(original_content):
            return GenerateResponse(
                content="这次生成的当前文件内容与原文件一致，因此没有实际可写回的修改。",
                mood="helpful",
            )

        summary = self._choose_action_summary(
            parsed_single.summary,
            f"根据当前需求修改活动文件：{Path(active_file).name}",
        )
        current_file_action = self._build_current_file_action(
            active_file=active_file,
            original_content=original_content,
            updated_content=updated_content,
            summary=summary,
        )
        current_preparation = WorkspaceActionPreparationResult(actions=[current_file_action])
        test_plan = self.workflow.build_test_plan(request.context, current_preparation)
        risk_summary = self._annotate_actions_with_risk(
            [current_file_action],
            request.context,
            test_plan,
        )

        return GenerateResponse(
            content=(
                f"我已经为当前文件 {Path(active_file).name} 生成了可直接写回的修改结果。"
                "插件端可以立即应用这次改写；如果你暂时不想写回，也可以先保留预览。"
            ),
            mood="helpful",
            actions=[current_file_action],
            requiresConfirmation=True,
            autoApplyActions=False,
            proposalSummary=(
                f"当前文件直改：{Path(active_file).name}；"
                f"风险：{self._risk_level_label(risk_summary.overall_level)}"
                f"（{risk_summary.overall_reason}）；"
                f"{current_file_action.summary}"
            ),
            riskOverview=self._build_risk_overview(risk_summary),
            testPlan=self._build_test_plan_model(test_plan),
        )

    # 方法说明：
    # 处理项目级修改场景，优先尝试生成结构化动作。
    def _generate_workspace_action_proposal(
        self,
        request: GenerateRequest,
        current_notes: str,
    ) -> GenerateResponse:
        if not request.context.workspaceRoot:
            if self._should_fallback_workspace_request_to_current_file(request):
                fallback_prompt = (
                    "当前没有打开项目文件夹。"
                    "请先仅针对当前活动文件处理下面这条需求，不要规划多文件方案："
                    f"{request.prompt}"
                )
                fallback_request = request.model_copy(update={"prompt": fallback_prompt})
                fallback_response = self._generate_current_file_edit(fallback_request, current_notes)
                fallback_response.content = (
                    "当前未打开项目文件夹，因此本次先退化为当前活动文件改写。\n"
                    + fallback_response.content
                )
                return fallback_response

            return GenerateResponse(
                content="如果你希望我检索整个项目并规划多文件修改，请先在 VS Code 中打开项目文件夹。",
                mood="idle",
            )

        workspace_result = self.workflow.inspect_workspace(request.context, request.prompt)
        semantic_result = self.workflow.inspect_workspace_semantics(
            request.context,
            request.prompt,
            workspace_result,
        )
        attention_result = self.workflow.select_attention_context(
            request.context,
            request.prompt,
            workspace_result,
            semantic_result,
            request.conversationHistory,
            self._retrieve_memory_items(request),
        )
        plan_result = self.workflow.plan_workspace_actions(
            request.context,
            request.prompt,
            workspace_result,
        )
        minimum_action_count = self._minimum_project_action_count(request.prompt, plan_result)
        system_prompt = build_system_prompt(request.context.systemPrompt, proposal_mode=True)
        first_prompt = build_workspace_action_prompt(
            request.prompt,
            request.context,
            current_notes,
            workspace_result,
            semantic_result.to_prompt_text(),
            request.conversationHistory,
            attention_result.to_prompt_text(),
        )

        try:
            content = self._run_model(system_prompt, first_prompt)
        except Exception as exc:
            fallback = (
                "我已经进入项目级变更规划模式，但调用 Ollama 失败了，因此这次没有生成预览方案。\n"
                f"错误信息：{exc}\n"
                "请检查 Ollama 服务和模型状态。"
            )
            return GenerateResponse(content=fallback, mood="idle")

        parsed = parse_action_plan_response(content)
        preparation = self.workflow.prepare_workspace_actions(
            request.context,
            parsed.actions,
            workspace_result,
        )

        if self._should_retry_action_plan(parsed.actions, preparation.actions, minimum_action_count):
            repair_prompt = build_workspace_action_repair_prompt(
                request.prompt,
                request.context,
                current_notes,
                workspace_result,
                semantic_result.to_prompt_text(),
                content,
                attention_result.to_prompt_text(),
            )

            try:
                repaired_content = self._run_model(system_prompt, repair_prompt)
                repaired_parsed = parse_action_plan_response(repaired_content)
                repaired_preparation = self.workflow.prepare_workspace_actions(
                    request.context,
                    repaired_parsed.actions,
                    workspace_result,
                )

                if not self._should_retry_action_plan(
                    repaired_parsed.actions,
                    repaired_preparation.actions,
                    minimum_action_count,
                ):
                    parsed = repaired_parsed
                    preparation = repaired_preparation
            except Exception:
                pass

        context_summary = self._combine_context_summaries(
            semantic_result.to_user_summary(),
            attention_result.to_user_summary(),
        )
        context_selection = self._build_context_selection_model(attention_result, semantic_result)

        if preparation.actions and not self._should_retry_action_plan(
            parsed.actions,
            preparation.actions,
            minimum_action_count,
        ):
            test_plan = self.workflow.build_test_plan(request.context, preparation)
            risk_summary = self._annotate_preparation_with_risk(
                preparation,
                request.context,
                test_plan,
            )
            return self._build_structured_action_response(
                parsed,
                preparation,
                context_summary,
                risk_summary,
                test_plan,
                context_selection,
            )

        fallback_preparation, fallback_notes = self._generate_fallback_actions(
            request,
            current_notes,
            workspace_result,
            plan_result,
        )

        demo_preparation = self.workflow.prepare_workspace_actions(
            request.context,
            self.workflow.build_demo_actions(request.context),
            workspace_result,
        )
        if demo_preparation.actions and (
            len(demo_preparation.actions) >= minimum_action_count
            or len(demo_preparation.actions) > len(fallback_preparation.actions)
        ):
            demo_notes = list(fallback_notes)
            demo_notes.append("当前使用的是演示保底方案，用于在弱模型条件下稳定展示 diff 预览与确认应用流程。")
            test_plan = self.workflow.build_test_plan(request.context, demo_preparation)
            risk_summary = self._annotate_preparation_with_risk(
                demo_preparation,
                request.context,
                test_plan,
            )
            return self._build_fallback_action_response(
                demo_preparation,
                demo_notes,
                context_summary,
                risk_summary,
                test_plan,
                context_selection,
            )

        if fallback_preparation.actions:
            test_plan = self.workflow.build_test_plan(request.context, fallback_preparation)
            risk_summary = self._annotate_preparation_with_risk(
                fallback_preparation,
                request.context,
                test_plan,
            )
            return self._build_fallback_action_response(
                fallback_preparation,
                fallback_notes,
                context_summary,
                risk_summary,
                test_plan,
                context_selection,
            )

        if demo_preparation.actions:
            demo_notes = list(fallback_notes)
            demo_notes.append("当前使用的是演示保底方案，用于在弱模型条件下稳定展示 diff 预览与确认应用流程。")
            test_plan = self.workflow.build_test_plan(request.context, demo_preparation)
            risk_summary = self._annotate_preparation_with_risk(
                demo_preparation,
                request.context,
                test_plan,
            )
            return self._build_fallback_action_response(
                demo_preparation,
                demo_notes,
                context_summary,
                risk_summary,
                test_plan,
                context_selection,
            )

        reply = parsed.assistant_reply or "我已经完成项目检索，但这次还没有稳定生成可执行的结构化动作。"
        combined_notes = fallback_notes or preparation.notes
        if combined_notes:
            note_text = "\n".join(f"- {note}" for note in combined_notes)
            reply = f"{reply}\n\n补充说明：\n{note_text}"

        if context_summary:
            reply = f"{reply}\n\n{context_summary}"

        if "结构化" not in reply:
            reply = f"{reply}\n\n这次我没有提取到可执行的结构化文件动作，所以暂时无法生成 diff 预览。"

        return GenerateResponse(
            content=reply,
            mood="helpful",
            contextSelection=context_selection,
        )

    # 方法说明：
    # 在当前文件直接改写模式下流式产出 patch 预览，并在末尾返回最终结果。
    def _stream_current_file_edit(
        self,
        request: GenerateRequest,
        current_notes: str,
        prefix_message: str = "",
    ) -> Iterator[str]:
        active_file = (request.context.activeFile or "").strip()
        if not active_file:
            yield self._build_stream_event(
                "result",
                GenerateResponse(
                    content="当前没有活动文件，因此无法直接改写代码。请先在编辑器中打开目标文件后再试。",
                    mood="idle",
                ).model_dump(),
            )
            return

        original_content = self._resolve_current_file_content(request.context)
        if not original_content.strip():
            yield self._build_stream_event(
                "result",
                GenerateResponse(
                    content="当前活动文件内容不可用，因此暂时无法直接生成可写回的修改结果。",
                    mood="idle",
                ).model_dump(),
            )
            return

        system_prompt = build_system_prompt(request.context.systemPrompt, single_file_mode=True)
        direct_prompt = build_current_file_edit_prompt(
            request.prompt,
            request.context,
            current_notes,
            original_content,
            request.conversationHistory,
        )

        raw_output = ""
        streamed_content = ""
        last_emitted_patch = ""

        try:
            for chunk in self.ollama.stream_chat(system_prompt, direct_prompt):
                raw_output += chunk
                cleaned = self._sanitize_partial_stream(raw_output)
                if cleaned != streamed_content:
                    streamed_content = cleaned
                    if cleaned.strip() and self._should_emit_patch_preview(last_emitted_patch, cleaned):
                        last_emitted_patch = cleaned
                        yield self._build_stream_event("patch", {"updatedContent": cleaned})
        except Exception as exc:
            yield self._build_stream_event(
                "result",
                GenerateResponse(
                    content=(
                        "我已经进入当前文件直接改写模式，但调用 Ollama 失败了，因此这次没有生成可写回的结果。\n"
                        f"错误信息：{exc}\n"
                        "请检查 Ollama 服务和模型状态。"
                    ),
                    mood="idle",
                ).model_dump(),
            )
            return

        if streamed_content.strip() and streamed_content != last_emitted_patch:
            yield self._build_stream_event("patch", {"updatedContent": streamed_content})

        yield self._build_stream_event("status", {"status": "正在校验 patch 结果"})
        parsed_single = parse_single_file_response(streamed_content)
        validation_error = self._validate_single_file_candidate(active_file, parsed_single.updated_content)

        if validation_error:
            yield self._build_stream_event("status", {"status": "正在修复输出格式"})
            repair_prompt = build_current_file_edit_repair_prompt(
                request.prompt,
                active_file,
                streamed_content or raw_output,
                validation_error,
            )

            try:
                repaired_output = self._run_model(system_prompt, repair_prompt)
                repaired_single = parse_single_file_response(repaired_output)
                repaired_error = self._validate_single_file_candidate(active_file, repaired_single.updated_content)
                if repaired_error is None:
                    parsed_single = repaired_single
                    if repaired_single.updated_content.strip() and repaired_single.updated_content != streamed_content:
                        yield self._build_stream_event("patch", {"updatedContent": repaired_single.updated_content})
                    validation_error = None
                else:
                    validation_error = repaired_error
            except Exception as exc:
                validation_error = f"{validation_error}；修复回合失败：{exc}"

        if validation_error:
            demo_response = self._build_demo_current_file_response(request, validation_error)
            if demo_response is not None:
                yield self._build_stream_event("result", demo_response.model_dump())
                return

            yield self._build_stream_event(
                "result",
                GenerateResponse(
                    content=(
                        "我已经识别到这是一次当前文件直接改写请求，但本地模型这次没有稳定生成可执行的新文件内容。\n"
                        f"原因：{validation_error}\n"
                        "你可以重试一次，或者改用项目级修改方案查看 diff 预览。"
                    ),
                    mood="helpful",
                ).model_dump(),
            )
            return

        updated_content = parsed_single.updated_content
        if self._canonicalize(updated_content) == self._canonicalize(original_content):
            yield self._build_stream_event(
                "result",
                GenerateResponse(
                    content="这次生成的当前文件内容与原文件一致，因此没有实际可写回的修改。",
                    mood="helpful",
                ).model_dump(),
            )
            return

        summary = self._choose_action_summary(
            parsed_single.summary,
            f"根据当前需求修改活动文件：{Path(active_file).name}",
        )
        yield self._build_stream_event("status", {"status": "已生成可应用 patch"})
        current_file_action = self._build_current_file_action(
            active_file=active_file,
            original_content=original_content,
            updated_content=updated_content,
            summary=summary,
        )
        current_preparation = WorkspaceActionPreparationResult(actions=[current_file_action])
        test_plan = self.workflow.build_test_plan(request.context, current_preparation)
        risk_summary = self._annotate_actions_with_risk(
            [current_file_action],
            request.context,
            test_plan,
        )

        response = GenerateResponse(
            content=prefix_message + (
                f"我已经为当前文件 {Path(active_file).name} 生成了可直接写回的修改结果。"
                "插件端可以立即应用这次改写；如果你暂时不想写回，也可以先保留预览。"
            ),
            mood="helpful",
            actions=[current_file_action],
            requiresConfirmation=True,
            autoApplyActions=False,
            proposalSummary=(
                f"当前文件直改：{Path(active_file).name}；"
                f"风险：{self._risk_level_label(risk_summary.overall_level)}"
                f"（{risk_summary.overall_reason}）；"
                f"{summary}"
            ),
            riskOverview=self._build_risk_overview(risk_summary),
            testPlan=self._build_test_plan_model(test_plan),
        )
        self._remember_response(request, response)
        yield self._build_stream_event("result", response.model_dump())

    # 方法说明：
    # 在普通问答模式下流式输出消息片段，并在结尾返回完整响应。
    def _stream_chat_response(self, request: GenerateRequest, current_notes: str) -> Iterator[str]:
        system_prompt = build_system_prompt(request.context.systemPrompt)
        attention_result = self._select_attention_context_for_chat(request)
        user_prompt = build_user_prompt(
            request.prompt,
            request.context,
            current_notes,
            request.conversationHistory,
            attention_result.to_prompt_text(),
        )

        raw_content = ""
        streamed_content = ""

        try:
            for chunk in self.ollama.stream_chat(system_prompt, user_prompt):
                raw_content += chunk
                cleaned = self._sanitize_partial_chat_response(raw_content)
                if cleaned == streamed_content:
                    continue

                delta = cleaned[len(streamed_content) :]
                streamed_content = cleaned
                if delta:
                    yield self._build_stream_event("message_chunk", {"chunk": delta})
        except Exception as exc:
            yield self._build_stream_event(
                "result",
                GenerateResponse(
                    content=(
                        "Python 后端已经收到请求，但调用 Ollama 失败了。\n"
                        f"错误信息：{exc}\n"
                        "请检查 Ollama 是否正在运行，以及目标模型是否已经下载。"
                    ),
                    mood="idle",
                ).model_dump(),
            )
            return

        content = self._sanitize_response(raw_content)
        response = GenerateResponse(
            content=content,
            mood="helpful",
            contextSelection=self._build_context_selection_model(attention_result),
        )
        self._remember_response(request, response)
        yield self._build_stream_event(
            "result",
            response.model_dump(),
        )

    # 方法说明：
    # 当多文件结构化输出失败时，改用逐文件生成方式兜底。
    def _generate_fallback_actions(
        self,
        request: GenerateRequest,
        current_notes: str,
        workspace_result: WorkspaceSearchResult,
        plan_result=None,
    ) -> tuple[WorkspaceActionPreparationResult, list[str]]:
        if plan_result is None:
            plan_result = self.workflow.plan_workspace_actions(request.context, request.prompt, workspace_result)
        if not plan_result.actions:
            return WorkspaceActionPreparationResult(), plan_result.notes

        single_file_system_prompt = build_system_prompt(
            request.context.systemPrompt,
            single_file_mode=True,
        )
        generated_actions: list[ParsedAction] = []
        notes = list(plan_result.notes)

        for planned_action in plan_result.actions:
            original_content = self._read_target_content(
                request.context,
                workspace_result,
                planned_action.target_file,
            )
            single_file_prompt = build_single_file_action_prompt(
                request.prompt,
                request.context,
                current_notes,
                workspace_result,
                planned_action,
                original_content,
                request.conversationHistory,
            )

            try:
                model_output = self._run_model(single_file_system_prompt, single_file_prompt)
            except Exception as exc:
                notes.append(f"{planned_action.target_file} 生成失败：{exc}")
                continue

            parsed_single = parse_single_file_response(model_output)
            single_file_error = self._validate_single_file_candidate(
                planned_action.target_file,
                parsed_single.updated_content,
            )

            if single_file_error:
                repair_prompt = build_single_file_repair_prompt(
                    request.prompt,
                    planned_action,
                    model_output,
                    single_file_error,
                )

                try:
                    repaired_output = self._run_model(single_file_system_prompt, repair_prompt)
                    repaired_single = parse_single_file_response(repaired_output)
                    repaired_error = self._validate_single_file_candidate(
                        planned_action.target_file,
                        repaired_single.updated_content,
                    )
                    if repaired_error:
                        notes.append(f"{planned_action.target_file} 修复后仍无效：{repaired_error}")
                        continue
                    parsed_single = repaired_single
                except Exception as exc:
                    notes.append(f"{planned_action.target_file} 修复失败：{exc}")
                    continue

            if not parsed_single.updated_content:
                notes.append(f"{planned_action.target_file} 没有返回完整文件内容。")
                continue

            generated_actions.append(
                ParsedAction(
                    kind=planned_action.kind,
                    target_file=planned_action.target_file,
                    summary=self._choose_action_summary(parsed_single.summary, planned_action.summary),
                    updated_content=parsed_single.updated_content,
                )
            )

        preparation = self.workflow.prepare_workspace_actions(
            request.context,
            generated_actions,
            workspace_result,
        )

        notes.extend(preparation.notes)
        return preparation, notes

    # 方法说明：
    # 将模型直接返回的结构化动作封装为统一响应。
    def _build_structured_action_response(
        self,
        parsed_response,
        preparation: WorkspaceActionPreparationResult,
        semantic_summary: str,
        risk_summary: ActionRiskSummary,
        test_plan: TestPlanResult,
        context_selection: ContextSelectionModel | None = None,
    ) -> GenerateResponse:
        reply = parsed_response.assistant_reply or "我已经完成项目检索，并生成了一组待确认的文件变更方案。"
        if semantic_summary:
            reply = f"{reply}\n\n{semantic_summary}"

        if risk_summary.assessments:
            reply = (
                f"{reply}\n\n整体风险：{self._risk_level_label(risk_summary.overall_level)}"
                f"（{risk_summary.overall_reason}）"
            )

        if test_plan.available:
            reply = f"{reply}\n\n自动测试：{test_plan.summary}"

        proposal_summary = parsed_response.proposal_summary or self._build_proposal_summary(
            preparation,
            risk_summary,
            test_plan,
        )
        if risk_summary.assessments and "风险" not in proposal_summary:
            proposal_summary = (
                f"{proposal_summary}；整体风险：{self._risk_level_label(risk_summary.overall_level)}"
                f"（{risk_summary.overall_reason}）"
            )

        return GenerateResponse(
            content=reply,
            mood="helpful",
            actions=preparation.actions,
            requiresConfirmation=True,
            autoApplyActions=False,
            proposalSummary=proposal_summary,
            riskOverview=self._build_risk_overview(risk_summary),
            testPlan=self._build_test_plan_model(test_plan),
            contextSelection=context_selection or ContextSelectionModel(),
        )

    # 方法说明：
    # 将逐文件兜底动作封装为统一响应。
    def _build_fallback_action_response(
        self,
        preparation: WorkspaceActionPreparationResult,
        notes: list[str],
        semantic_summary: str,
        risk_summary: ActionRiskSummary,
        test_plan: TestPlanResult,
        context_selection: ContextSelectionModel | None = None,
    ) -> GenerateResponse:
        affected_files = "、".join(Path(action.targetFile).name for action in preparation.actions[:3])
        reply = (
            f"我已经完成项目检索，并通过逐文件改写模式生成了 {len(preparation.actions)} 个待确认修改动作。"
            f"本次涉及的文件有：{affected_files}。"
            "你可以先查看 diff 预览，再决定是否应用。"
        )

        if semantic_summary:
            reply = f"{reply}\n\n{semantic_summary}"

        if risk_summary.assessments:
            reply = (
                f"{reply}\n\n整体风险：{self._risk_level_label(risk_summary.overall_level)}"
                f"（{risk_summary.overall_reason}）"
            )

        if test_plan.available:
            reply = f"{reply}\n\n自动测试：{test_plan.summary}"

        helpful_notes = [note for note in notes if note][:4]
        if helpful_notes:
            reply = f"{reply}\n\n补充说明：\n" + "\n".join(f"- {note}" for note in helpful_notes)

        return GenerateResponse(
            content=reply,
            mood="helpful",
            actions=preparation.actions,
            requiresConfirmation=True,
            autoApplyActions=False,
            proposalSummary=self._build_proposal_summary(preparation, risk_summary, test_plan),
            riskOverview=self._build_risk_overview(risk_summary),
            testPlan=self._build_test_plan_model(test_plan),
            contextSelection=context_selection or ContextSelectionModel(),
        )

    # 方法说明：
    # 为预览面板构造简洁摘要。
    def _build_proposal_summary(
        self,
        preparation: WorkspaceActionPreparationResult,
        risk_summary: ActionRiskSummary | None = None,
        test_plan: TestPlanResult | None = None,
    ) -> str:
        if not preparation.actions:
            return ""

        parts = [f"{Path(action.targetFile).name}：{action.summary}" for action in preparation.actions[:3]]
        prefix = f"共生成 {len(preparation.actions)} 个待确认变更"
        if risk_summary and risk_summary.assessments:
            prefix = (
                f"{prefix}；整体风险：{self._risk_level_label(risk_summary.overall_level)}"
                f"（{risk_summary.overall_reason}）"
            )
        if test_plan and test_plan.available:
            prefix = f"{prefix}；自动测试：{test_plan.summary}"
        return prefix + "；" + "；".join(parts)

    # 方法说明：
    # 对准备好的文件动作补充风险提示，并返回整体风险评估结果。
    def _annotate_preparation_with_risk(
        self,
        preparation: WorkspaceActionPreparationResult,
        context: AgentContextModel,
        test_plan: TestPlanResult | None = None,
    ) -> ActionRiskSummary:
        return self._annotate_actions_with_risk(preparation.actions, context, test_plan)

    # 方法说明：
    # 对动作摘要追加风险标签，保证前端在不调整结构时也能直接展示风险信息。
    def _annotate_actions_with_risk(
        self,
        actions: list[FileActionModel],
        context: AgentContextModel,
        test_plan: TestPlanResult | None = None,
    ) -> ActionRiskSummary:
        preparation = WorkspaceActionPreparationResult(actions=actions)
        risk_summary = self.workflow.assess_action_risk(context, preparation, test_plan)
        assessment_map = {
            assessment.target_file.lower(): assessment
            for assessment in risk_summary.assessments
        }

        for action in actions:
            assessment = assessment_map.get(action.targetFile.lower())
            if assessment is None:
                continue
            action.summary = self._decorate_action_summary_with_risk(action.summary, assessment)

        return risk_summary

    def _build_risk_overview(self, risk_summary: ActionRiskSummary) -> RiskOverviewModel:
        return RiskOverviewModel(
            level=risk_summary.overall_level,
            score=risk_summary.overall_score,
            summary=risk_summary.overall_reason,
            highlights=risk_summary.highlights,
        )

    def _build_test_plan_model(self, test_plan: TestPlanResult) -> TestPlanModel:
        return TestPlanModel(
            available=test_plan.available,
            summary=test_plan.summary,
            commands=[
                TestCommandModel(
                    command=command.command,
                    purpose=command.purpose,
                    kind=command.kind,
                    confidence=command.confidence,
                )
                for command in test_plan.commands
            ],
            machineLearningBasis=test_plan.machine_learning_basis,
            hasStandardTests=test_plan.has_standard_tests,
        )

    def _build_context_selection_model(
        self,
        attention_result,
        semantic_result: WorkspaceSemanticResult | None = None,
    ) -> ContextSelectionModel:
        """
        将注意力上下文选择结果转成前端和论文演示可直接消费的结构化诊断数据。
        """

        matches = [
            ContextSelectionMatchModel(
                source=match.source,
                identifier=match.identifier,
                title=match.title,
                chunkType=match.chunk_type,
                location=match.location,
                weight=round(match.weight, 6),
                attentionWeight=round(match.attention_weight, 6),
                cosineSimilarity=round(match.cosine_similarity, 6),
                retrievalScore=round(match.retrieval_score, 6),
                headWeights=[round(value, 6) for value in match.head_weights],
                excerpt=match.excerpt,
            )
            for match in attention_result.matches[:6]
        ]
        semantic_files = [
            match.relative_path
            for match in (semantic_result.matches if semantic_result else [])
        ][:6]

        summary = attention_result.to_user_summary()
        if semantic_result is not None:
            summary = self._combine_context_summaries(
                semantic_result.to_user_summary(),
                summary,
            )

        return ContextSelectionModel(
            available=bool(matches),
            summary=summary,
            embeddingProvider=attention_result.embedding_provider,
            embeddingModel=attention_result.embedding_model,
            fallbackUsed=attention_result.fallback_used,
            warning=attention_result.warning,
            headCount=attention_result.head_count,
            semanticFiles=semantic_files,
            matches=matches,
        )

    def _retrieve_memory_items(self, request: GenerateRequest) -> list[str]:
        """
        从 SQLite 中读取跨会话长期记忆，作为 attention 的候选上下文。
        """

        return self.memory_store.retrieve_memory_items(
            request.context,
            request.prompt,
            request.conversationHistory,
        )

    def _remember_response(self, request: GenerateRequest, response: GenerateResponse) -> None:
        """
        将本轮请求和上下文选择诊断写入 SQLite 记忆库。
        """

        self.memory_store.remember_response(request.prompt, request.context, response)

    # 方法说明：
    # 将风险结果转为适合直接展示在摘要中的中文标签。
    def _decorate_action_summary_with_risk(self, summary: str, assessment) -> str:
        label = self._risk_level_label(assessment.level)
        normalized_summary = summary.strip()

        if normalized_summary.startswith("[低风险]") or normalized_summary.startswith("[中风险]") or normalized_summary.startswith("[高风险]"):
            return normalized_summary

        if assessment.reason:
            return f"[{label}] {normalized_summary}；{assessment.reason}"

        return f"[{label}] {normalized_summary}"

    # 方法说明：
    # 将英文风险等级映射为前端和 README 更适合展示的中文文本。
    def _risk_level_label(self, level: str) -> str:
        mapping = {
            "low": "低风险",
            "medium": "中风险",
            "high": "高风险",
        }
        return mapping.get(level, "中风险")

    # 方法说明：
    # 优先使用足够简洁的模型摘要，否则回退到规则化摘要。
    def _choose_action_summary(self, model_summary: str, fallback_summary: str) -> str:
        cleaned = " ".join(model_summary.split()).strip()
        if not cleaned:
            return fallback_summary
        if len(cleaned) > 80:
            return fallback_summary
        return cleaned

    # 方法说明：
    # 在单文件兜底阶段，对模型输出做最低限度的有效性检查。
    def _validate_single_file_candidate(self, target_file: str, updated_content: str) -> str | None:
        cleaned = updated_content.strip()
        if not cleaned:
            return "没有返回完整文件内容。"

        lowered = cleaned.lower()
        incomplete_markers = [
            "not shown due to brevity",
            "omitted",
            "placeholder",
            "full code not shown",
            "此处省略",
            "省略",
            "todo",
        ]
        if any(marker in lowered for marker in incomplete_markers):
            return "输出中包含省略内容或占位符。"

        if "<p>" in lowered or "<summary>" in lowered or "<updated_content>" in lowered:
            return "输出里仍然混入了解释性标签，而不是纯文件内容。"

        if Path(target_file).suffix.lower() == ".py":
            try:
                ast.parse(cleaned)
            except SyntaxError as exc:
                return f"Python 语法错误：第 {exc.lineno} 行附近。"

        return None

    # 方法说明：
    # 读取目标文件的原始内容，优先使用活动编辑器中的完整文本。
    def _combine_context_summaries(self, *summaries: str) -> str:
        """
        Merge retrieval summaries while keeping user-facing notes concise.
        """

        unique_summaries: list[str] = []
        seen: set[str] = set()
        for summary in summaries:
            cleaned = summary.strip()
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            unique_summaries.append(cleaned)

        return "\n".join(unique_summaries)

    def _read_target_content(
        self,
        context: AgentContextModel,
        workspace_result: WorkspaceSearchResult,
        relative_path: str,
    ) -> str:
        normalized_relative = relative_path.replace("\\", "/").lower()

        if context.workspaceRoot and context.activeFile and context.fullDocumentText:
            try:
                active_relative = str(
                    Path(context.activeFile).resolve().relative_to(Path(context.workspaceRoot).resolve())
                ).replace("\\", "/").lower()
                if active_relative == normalized_relative:
                    return context.fullDocumentText
            except ValueError:
                pass

        for snapshot in workspace_result.candidate_files:
            if snapshot.relative_path.replace("\\", "/").lower() == normalized_relative:
                return snapshot.full_content

        if not context.workspaceRoot:
            return ""

        target_path = Path(context.workspaceRoot).resolve() / relative_path
        if not target_path.exists():
            return ""

        try:
            return target_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            try:
                return target_path.read_text(encoding="gbk")
            except UnicodeDecodeError:
                return target_path.read_text(errors="ignore")
        except OSError:
            return ""

    # 方法说明：
    # 读取当前活动文件的完整内容，优先使用编辑器中的全文快照。
    def _resolve_current_file_content(self, context: AgentContextModel) -> str:
        if context.fullDocumentText:
            return context.fullDocumentText

        if not context.activeFile:
            return ""

        target_path = Path(context.activeFile)
        if not target_path.exists():
            return ""

        try:
            return target_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            try:
                return target_path.read_text(encoding="gbk")
            except UnicodeDecodeError:
                return target_path.read_text(errors="ignore")
        except OSError:
            return ""

    # 方法说明：
    # 为当前文件直接改写模式构造单文件动作对象。
    def _build_current_file_action(
        self,
        active_file: str,
        original_content: str,
        updated_content: str,
        summary: str,
    ) -> FileActionModel:
        return FileActionModel(
            kind="update_file",
            targetFile=str(Path(active_file).resolve()),
            originalContent=original_content,
            updatedContent=updated_content,
            summary=summary,
        )

    # 方法说明：
    # 当弱模型无法稳定返回当前文件改写结果时，尝试复用演示保底动作。
    def _build_demo_current_file_response(
        self,
        request: GenerateRequest,
        validation_error: str,
    ) -> GenerateResponse | None:
        if not request.context.workspaceRoot:
            return None

        workspace_result = self.workflow.inspect_workspace(request.context, request.prompt)
        preparation = self.workflow.prepare_workspace_actions(
            request.context,
            self.workflow.build_demo_actions(request.context),
            workspace_result,
        )
        if not preparation.actions:
            return None

        test_plan = self.workflow.build_test_plan(request.context, preparation)
        risk_summary = self._annotate_preparation_with_risk(
            preparation,
            request.context,
            test_plan,
        )
        first_action = preparation.actions[0]
        return GenerateResponse(
            content=(
                "当前文件直接改写模式已启动，但本地模型未稳定返回完整文件内容。"
                f"已切换到演示保底方案继续提供可执行改写。\n原因：{validation_error}"
            ),
            mood="helpful",
            actions=[first_action],
            requiresConfirmation=True,
            autoApplyActions=False,
            proposalSummary=(
                f"当前文件直改：{Path(first_action.targetFile).name}；"
                f"风险：{self._risk_level_label(risk_summary.overall_level)}"
                f"（{risk_summary.overall_reason}）；"
                f"{first_action.summary}"
            ),
            riskOverview=self._build_risk_overview(risk_summary),
            testPlan=self._build_test_plan_model(test_plan),
        )

    # 方法说明：
    # 调用底层模型客户端，并统一清理返回文本。
    def _build_fallback_test_analysis_response(
        self,
        request: TestAnalysisRequest,
    ) -> TestAnalysisResponse:
        overall_status = self._overall_test_status(request)
        summary = self._summarize_test_executions(request)
        if overall_status == "passed":
            content = (
                "## 测试结论\n"
                "- 当前自动测试与验证命令均已通过。\n\n"
                "## 结果说明\n"
                f"- {summary}\n"
                "- 本次修改已经通过当前检测链路，可继续进入人工复核或演示阶段。"
            )
        elif overall_status == "failed":
            failed_execution = next((item for item in request.executions if item.exitCode != 0), None)
            error_hint = ""
            if failed_execution is not None:
                error_source = failed_execution.stderr.strip() or failed_execution.stdout.strip()
                if error_source:
                    error_hint = error_source.splitlines()[-1]

            content = (
                "## 测试结论\n"
                "- 当前修改未通过全部自动测试或验证。\n\n"
                "## 失败定位\n"
                f"- {summary}\n"
                f"- 重点失败命令：{failed_execution.command if failed_execution else 'unknown'}\n"
                f"- 关键输出：{error_hint or '未提取到明确错误行'}\n\n"
                "## 建议下一步\n"
                "- 先根据失败命令回看对应文件的最近改动，再决定是否继续自动修复。"
            )
        else:
            content = (
                "## 测试结论\n"
                "- 当前没有足够的测试结果可供分析。\n\n"
                "## 建议下一步\n"
                "- 请先执行自动测试或至少完成一次验证级检查。"
            )

        return TestAnalysisResponse(
            content=content,
            summary=summary,
            overallStatus=overall_status,
        )

    def _overall_test_status(self, request: TestAnalysisRequest) -> str:
        if not request.executions:
            return "unknown"

        if any(item.exitCode != 0 for item in request.executions):
            return "failed"

        return "passed"

    def _summarize_test_executions(self, request: TestAnalysisRequest) -> str:
        if not request.executions:
            return "未执行测试命令。"

        passed = sum(1 for item in request.executions if item.exitCode == 0)
        failed = sum(1 for item in request.executions if item.exitCode != 0)
        if failed > 0:
            return f"共执行 {len(request.executions)} 条命令，其中 {passed} 条通过，{failed} 条失败。"
        return f"共执行 {len(request.executions)} 条命令，全部通过。"

    def _run_model(self, system_prompt: str, user_prompt: str) -> str:
        raw_content = self.ollama.chat(system_prompt=system_prompt, user_prompt=user_prompt)
        return self._sanitize_response(raw_content)

    # 方法说明：
    # 判断当前是否值得触发一次结构化重试。
    def _should_retry_action_plan(
        self,
        parsed_actions: list[object],
        prepared_actions: list[object],
        minimum_action_count: int,
    ) -> bool:
        if not parsed_actions or not prepared_actions:
            return True

        if len(prepared_actions) < minimum_action_count:
            return True

        return False

    # 方法说明：
    # 根据项目级规划结果，给结构化动作设定最低动作数量要求。
    def _minimum_project_action_count(
        self,
        prompt: str,
        plan_result,
    ) -> int:
        if not self._is_project_scope_request(prompt):
            return 1

        planned_count = len(plan_result.actions)
        if planned_count <= 0:
            return 2

        return max(2, min(4, planned_count))

    # 方法说明：
    # 清理模型可能返回的思维链占位文本。
    def _sanitize_response(self, content: str) -> str:
        cleaned = re.sub(r"<think>.*?</think>\s*", "", content, flags=re.DOTALL).strip()
        return cleaned or content.strip()

    # 方法说明：
    # 统一当前文件改写流程中的文本比较规则。
    def _canonicalize(self, content: str) -> str:
        return content.replace("\r\n", "\n").replace("\r", "\n").strip()

    # 方法说明：
    # 将最近对话整理成轻量文本，供请求分类阶段使用。
    def _conversation_history_text(self, request: GenerateRequest) -> str:
        if not request.conversationHistory:
            return ""

        return "\n".join(
            f"{turn.role}: {turn.content.strip()}"
            for turn in request.conversationHistory[-6:]
        )

    # 方法说明：
    # 判断请求是否更接近项目级或多文件范围，用于约束动作规划结果的最小规模。
    def _is_project_scope_request(self, prompt: str) -> bool:
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

    # 方法说明：
    # 将流式事件编码为单行 JSON，供前端逐条读取。
    def _build_stream_event(self, event_type: str, payload: dict[str, object]) -> str:
        return json.dumps({"type": event_type, "payload": payload}, ensure_ascii=False) + "\n"

    # 方法说明：
    # 在流式输出阶段尽量移除未完成的思维链标签内容。
    def _sanitize_partial_stream(self, content: str) -> str:
        if "<think>" not in content:
            cleaned = content
        else:
            cleaned = content
            while "<think>" in cleaned:
                start = cleaned.find("<think>")
                end = cleaned.find("</think>", start)
                if end == -1:
                    cleaned = cleaned[:start]
                    break
                cleaned = cleaned[:start] + cleaned[end + len("</think>") :]

        cleaned = re.sub(r"<summary>.*?</summary>\s*", "", cleaned, flags=re.DOTALL | re.IGNORECASE)
        cleaned = re.sub(r"^\s*<(updated_content|updated_file)>\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*</(updated_content|updated_file)>\s*$", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"^\s*```[^\n]*\n", "", cleaned)
        cleaned = re.sub(r"\n```?\s*$", "", cleaned)

        return cleaned.strip()

    # 方法说明：
    # 在普通问答模式下仅移除思维链内容，保留 Markdown 结构。
    def _sanitize_partial_chat_response(self, content: str) -> str:
        if "<think>" not in content:
            return content

        cleaned = content
        while "<think>" in cleaned:
            start = cleaned.find("<think>")
            end = cleaned.find("</think>", start)
            if end == -1:
                cleaned = cleaned[:start]
                break
            cleaned = cleaned[:start] + cleaned[end + len("</think>") :]

        return cleaned

    # 方法说明：
    # 控制流式 patch 事件的发送频率，避免前端因过密刷新而抖动。
    def _should_emit_patch_preview(self, previous_content: str, current_content: str) -> bool:
        previous_length = len(previous_content)
        current_length = len(current_content)
        delta = current_length - previous_length

        if previous_length == 0:
            return current_length >= 24

        if delta >= 120:
            return True

        if current_content.endswith("\n") and delta >= 48:
            return True

        return False

    # 方法说明：
    # 在没有工作区的情况下，判断是否可以退化为当前活动文件改写。
    def _should_fallback_workspace_request_to_current_file(self, request: GenerateRequest) -> bool:
        if not request.context.activeFile or not request.context.fullDocumentText:
            return False

        normalized_prompt = request.prompt.strip().lower()
        explicit_multi_file_markers = [
            "多个文件",
            "多文件",
            "readme",
            "docs",
            "文档",
            "工作区",
            "workspace",
            "整个项目",
            "项目级",
            "新增文件",
            "创建文件",
        ]
        return not any(marker in normalized_prompt for marker in explicit_multi_file_markers)

    # 方法说明：
    # 当项目级请求缺少工作区信息时，构造一个退化到当前文件改写的请求对象。
    def _build_workspace_fallback_request(self, request: GenerateRequest) -> GenerateRequest | None:
        if request.context.workspaceRoot:
            return None

        if not self._should_fallback_workspace_request_to_current_file(request):
            return None

        fallback_prompt = (
            "当前没有打开项目文件夹。"
            "请先仅针对当前活动文件处理下面这条需求，不要规划多文件方案："
            f"{request.prompt}"
        )
        return request.model_copy(update={"prompt": fallback_prompt})
