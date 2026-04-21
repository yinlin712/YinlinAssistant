import json
import ast
import re
from collections.abc import Iterator
from pathlib import Path

from backend.agent_workflow import AgentWorkflow
from backend.models import AgentContextModel, FileActionModel, GenerateRequest, GenerateResponse
from backend.ollama_client import OllamaClient
from backend.prompt_builder import (
    build_current_file_edit_prompt,
    build_current_file_edit_repair_prompt,
    build_single_file_action_prompt,
    build_single_file_repair_prompt,
    build_system_prompt,
    build_user_prompt,
    build_workspace_action_prompt,
    build_workspace_action_repair_prompt,
)
from backend.request_classifier import should_directly_edit_current_file, should_propose_workspace_changes
from backend.structured_response import ParsedAction, parse_action_plan_response, parse_single_file_response
from backend.tools.action_risk_tool import ActionRiskSummary
from backend.tools.workspace_action_tool import WorkspaceActionPreparationResult
from backend.tools.workspace_search_tool import WorkspaceSearchResult

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

    # 方法说明：
    # 这是后端对外暴露的统一入口。
    def generate(self, request: GenerateRequest) -> GenerateResponse:
        current_notes = self.workflow.inspect_current_context(request.context)
        conversation_history_text = self._conversation_history_text(request)

        if should_directly_edit_current_file(
            request.prompt,
            request.context.selectedText or "",
            conversation_history_text,
        ):
            return self._generate_current_file_edit(request, current_notes)

        if should_propose_workspace_changes(
            request.prompt,
            request.context.selectedText or "",
            conversation_history_text,
        ):
            return self._generate_workspace_action_proposal(request, current_notes)

        return self._generate_chat_response(request, current_notes)

    # 方法说明：
    # 以流式事件形式执行请求，优先用于当前文件改写时的实时 patch 预览。
    def stream_generate(self, request: GenerateRequest) -> Iterator[str]:
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
            response = self.generate(request)
            yield self._build_stream_event("result", response.model_dump())
            return

        yield self._build_stream_event("status", {"status": "正在生成回复"})
        yield from self._stream_chat_response(request, current_notes)

    # 方法说明：
    # 处理普通问答场景，不涉及真实文件修改。
    def _generate_chat_response(self, request: GenerateRequest, current_notes: str) -> GenerateResponse:
        system_prompt = build_system_prompt(request.context.systemPrompt)
        user_prompt = build_user_prompt(
            request.prompt,
            request.context,
            current_notes,
            request.conversationHistory,
        )

        try:
            raw_content = self.ollama.chat(system_prompt=system_prompt, user_prompt=user_prompt)
            content = self._sanitize_response(raw_content)
            return GenerateResponse(content=content, mood="helpful")
        except Exception as exc:
            fallback = (
                "Python 后端已经收到请求，但调用 Ollama 失败了。\n"
                f"错误信息：{exc}\n"
                "请检查 Ollama 是否正在运行，以及目标模型是否已经下载。"
            )
            return GenerateResponse(content=fallback, mood="idle")

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
        risk_summary = self._annotate_actions_with_risk([current_file_action], request.context)

        return GenerateResponse(
            content=(
                f"我已经为当前文件 {Path(active_file).name} 生成了可直接写回的修改结果。"
                "插件端可以立即应用这次改写；如果你暂时不想写回，也可以先保留预览。"
            ),
            mood="helpful",
            actions=[current_file_action],
            requiresConfirmation=True,
            autoApplyActions=True,
            proposalSummary=(
                f"当前文件直改：{Path(active_file).name}；"
                f"风险：{self._risk_level_label(risk_summary.overall_level)}"
                f"（{risk_summary.overall_reason}）；"
                f"{current_file_action.summary}"
            ),
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

        if preparation.actions and not self._should_retry_action_plan(
            parsed.actions,
            preparation.actions,
            minimum_action_count,
        ):
            risk_summary = self._annotate_preparation_with_risk(preparation, request.context)
            return self._build_structured_action_response(
                parsed,
                preparation,
                semantic_result.to_user_summary(),
                risk_summary,
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
            risk_summary = self._annotate_preparation_with_risk(demo_preparation, request.context)
            return self._build_fallback_action_response(
                demo_preparation,
                demo_notes,
                semantic_result.to_user_summary(),
                risk_summary,
            )

        if fallback_preparation.actions:
            risk_summary = self._annotate_preparation_with_risk(fallback_preparation, request.context)
            return self._build_fallback_action_response(
                fallback_preparation,
                fallback_notes,
                semantic_result.to_user_summary(),
                risk_summary,
            )

        if demo_preparation.actions:
            demo_notes = list(fallback_notes)
            demo_notes.append("当前使用的是演示保底方案，用于在弱模型条件下稳定展示 diff 预览与确认应用流程。")
            risk_summary = self._annotate_preparation_with_risk(demo_preparation, request.context)
            return self._build_fallback_action_response(
                demo_preparation,
                demo_notes,
                semantic_result.to_user_summary(),
                risk_summary,
            )

        reply = parsed.assistant_reply or "我已经完成项目检索，但这次还没有稳定生成可执行的结构化动作。"
        combined_notes = fallback_notes or preparation.notes
        if combined_notes:
            note_text = "\n".join(f"- {note}" for note in combined_notes)
            reply = f"{reply}\n\n补充说明：\n{note_text}"

        semantic_summary = semantic_result.to_user_summary()
        if semantic_summary:
            reply = f"{reply}\n\n{semantic_summary}"

        if "结构化" not in reply:
            reply = f"{reply}\n\n这次我没有提取到可执行的结构化文件动作，所以暂时无法生成 diff 预览。"

        return GenerateResponse(content=reply, mood="helpful")

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
        response = GenerateResponse(
            content=prefix_message + (
                f"我已经为当前文件 {Path(active_file).name} 生成了可直接写回的修改结果。"
                "插件端可以立即应用这次改写；如果你暂时不想写回，也可以先保留预览。"
            ),
            mood="helpful",
            actions=[
                self._build_current_file_action(
                    active_file=active_file,
                    original_content=original_content,
                    updated_content=updated_content,
                    summary=summary,
                )
            ],
            requiresConfirmation=True,
            autoApplyActions=True,
            proposalSummary=f"当前文件直改：{Path(active_file).name}；{summary}",
        )
        yield self._build_stream_event("result", response.model_dump())

    # 方法说明：
    # 在普通问答模式下流式输出消息片段，并在结尾返回完整响应。
    def _stream_chat_response(self, request: GenerateRequest, current_notes: str) -> Iterator[str]:
        system_prompt = build_system_prompt(request.context.systemPrompt)
        user_prompt = build_user_prompt(
            request.prompt,
            request.context,
            current_notes,
            request.conversationHistory,
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
        yield self._build_stream_event(
            "result",
            GenerateResponse(content=content, mood="helpful").model_dump(),
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
    ) -> GenerateResponse:
        reply = parsed_response.assistant_reply or "我已经完成项目检索，并生成了一组待确认的文件变更方案。"
        if semantic_summary:
            reply = f"{reply}\n\n{semantic_summary}"

        if risk_summary.assessments:
            reply = (
                f"{reply}\n\n整体风险：{self._risk_level_label(risk_summary.overall_level)}"
                f"（{risk_summary.overall_reason}）"
            )

        proposal_summary = parsed_response.proposal_summary or self._build_proposal_summary(
            preparation,
            risk_summary,
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
        )

    # 方法说明：
    # 将逐文件兜底动作封装为统一响应。
    def _build_fallback_action_response(
        self,
        preparation: WorkspaceActionPreparationResult,
        notes: list[str],
        semantic_summary: str,
        risk_summary: ActionRiskSummary,
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

        helpful_notes = [note for note in notes if note][:4]
        if helpful_notes:
            reply = f"{reply}\n\n补充说明：\n" + "\n".join(f"- {note}" for note in helpful_notes)

        return GenerateResponse(
            content=reply,
            mood="helpful",
            actions=preparation.actions,
            requiresConfirmation=True,
            autoApplyActions=False,
            proposalSummary=self._build_proposal_summary(preparation, risk_summary),
        )

    # 方法说明：
    # 为预览面板构造简洁摘要。
    def _build_proposal_summary(
        self,
        preparation: WorkspaceActionPreparationResult,
        risk_summary: ActionRiskSummary | None = None,
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
        return prefix + "；" + "；".join(parts)

    # 方法说明：
    # 对准备好的文件动作补充风险提示，并返回整体风险评估结果。
    def _annotate_preparation_with_risk(
        self,
        preparation: WorkspaceActionPreparationResult,
        context: AgentContextModel,
    ) -> ActionRiskSummary:
        return self._annotate_actions_with_risk(preparation.actions, context)

    # 方法说明：
    # 对动作摘要追加风险标签，保证前端在不调整结构时也能直接展示风险信息。
    def _annotate_actions_with_risk(
        self,
        actions: list[FileActionModel],
        context: AgentContextModel,
    ) -> ActionRiskSummary:
        preparation = WorkspaceActionPreparationResult(actions=actions)
        risk_summary = self.workflow.assess_action_risk(context, preparation)
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

        risk_summary = self._annotate_preparation_with_risk(preparation, request.context)
        first_action = preparation.actions[0]
        return GenerateResponse(
            content=(
                "当前文件直接改写模式已启动，但本地模型未稳定返回完整文件内容。"
                f"已切换到演示保底方案继续提供可执行改写。\n原因：{validation_error}"
            ),
            mood="helpful",
            actions=[first_action],
            requiresConfirmation=True,
            autoApplyActions=True,
            proposalSummary=(
                f"当前文件直改：{Path(first_action.targetFile).name}；"
                f"风险：{self._risk_level_label(risk_summary.overall_level)}"
                f"（{risk_summary.overall_reason}）；"
                f"{first_action.summary}"
            ),
        )

    # 方法说明：
    # 调用底层模型客户端，并统一清理返回文本。
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
