import ast
import re
from pathlib import Path

from backend.agent_workflow import AgentWorkflow
from backend.models import AgentContextModel, GenerateRequest, GenerateResponse
from backend.ollama_client import OllamaClient
from backend.prompt_builder import (
    build_single_file_action_prompt,
    build_single_file_repair_prompt,
    build_system_prompt,
    build_user_prompt,
    build_workspace_action_prompt,
    build_workspace_action_repair_prompt,
)
from backend.request_classifier import should_propose_workspace_changes
from backend.structured_response import ParsedAction, parse_action_plan_response, parse_single_file_response
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

        if should_propose_workspace_changes(request.prompt):
            return self._generate_workspace_action_proposal(request, current_notes)

        return self._generate_chat_response(request, current_notes)

    # 方法说明：
    # 处理普通问答场景，不涉及真实文件修改。
    def _generate_chat_response(self, request: GenerateRequest, current_notes: str) -> GenerateResponse:
        system_prompt = build_system_prompt(request.context.systemPrompt)
        user_prompt = build_user_prompt(request.prompt, request.context, current_notes)

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
    # 处理项目级修改场景，优先尝试生成结构化动作。
    def _generate_workspace_action_proposal(
        self,
        request: GenerateRequest,
        current_notes: str,
    ) -> GenerateResponse:
        if not request.context.workspaceRoot:
            return GenerateResponse(
                content="如果你希望我检索整个项目并规划多文件修改，请先在 VS Code 中打开项目文件夹。",
                mood="idle",
            )

        workspace_result = self.workflow.inspect_workspace(request.context, request.prompt)
        system_prompt = build_system_prompt(request.context.systemPrompt, proposal_mode=True)
        first_prompt = build_workspace_action_prompt(
            request.prompt,
            request.context,
            current_notes,
            workspace_result,
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

        if self._should_retry_action_plan(parsed.actions, preparation.actions):
            repair_prompt = build_workspace_action_repair_prompt(
                request.prompt,
                request.context,
                current_notes,
                workspace_result,
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

                if repaired_preparation.actions:
                    parsed = repaired_parsed
                    preparation = repaired_preparation
            except Exception:
                pass

        if preparation.actions:
            return self._build_structured_action_response(parsed, preparation)

        fallback_preparation, fallback_notes = self._generate_fallback_actions(
            request,
            current_notes,
            workspace_result,
        )

        if fallback_preparation.actions:
            return self._build_fallback_action_response(fallback_preparation, fallback_notes)

        demo_preparation = self.workflow.prepare_workspace_actions(
            request.context,
            self.workflow.build_demo_actions(request.context),
            workspace_result,
        )
        if demo_preparation.actions:
            demo_notes = list(fallback_notes)
            demo_notes.append("当前使用的是演示保底方案，用于在弱模型条件下稳定展示 diff 预览与确认应用流程。")
            return self._build_fallback_action_response(demo_preparation, demo_notes)

        reply = parsed.assistant_reply or "我已经完成项目检索，但这次还没有稳定生成可执行的结构化动作。"
        combined_notes = fallback_notes or preparation.notes
        if combined_notes:
            note_text = "\n".join(f"- {note}" for note in combined_notes)
            reply = f"{reply}\n\n补充说明：\n{note_text}"

        if "结构化" not in reply:
            reply = f"{reply}\n\n这次我没有提取到可执行的结构化文件动作，所以暂时无法生成 diff 预览。"

        return GenerateResponse(content=reply, mood="helpful")

    # 方法说明：
    # 当多文件结构化输出失败时，改用逐文件生成方式兜底。
    def _generate_fallback_actions(
        self,
        request: GenerateRequest,
        current_notes: str,
        workspace_result: WorkspaceSearchResult,
    ) -> tuple[WorkspaceActionPreparationResult, list[str]]:
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
    ) -> GenerateResponse:
        reply = parsed_response.assistant_reply or "我已经完成项目检索，并生成了一组待确认的文件变更方案。"
        proposal_summary = parsed_response.proposal_summary or self._build_proposal_summary(preparation)

        return GenerateResponse(
            content=reply,
            mood="helpful",
            actions=preparation.actions,
            requiresConfirmation=True,
            proposalSummary=proposal_summary,
        )

    # 方法说明：
    # 将逐文件兜底动作封装为统一响应。
    def _build_fallback_action_response(
        self,
        preparation: WorkspaceActionPreparationResult,
        notes: list[str],
    ) -> GenerateResponse:
        affected_files = "、".join(Path(action.targetFile).name for action in preparation.actions[:3])
        reply = (
            f"我已经完成项目检索，并通过逐文件改写模式生成了 {len(preparation.actions)} 个待确认修改动作。"
            f"本次涉及的文件有：{affected_files}。"
            "你可以先查看 diff 预览，再决定是否应用。"
        )

        helpful_notes = [note for note in notes if note][:4]
        if helpful_notes:
            reply = f"{reply}\n\n补充说明：\n" + "\n".join(f"- {note}" for note in helpful_notes)

        return GenerateResponse(
            content=reply,
            mood="helpful",
            actions=preparation.actions,
            requiresConfirmation=True,
            proposalSummary=self._build_proposal_summary(preparation),
        )

    # 方法说明：
    # 为预览面板构造简洁摘要。
    def _build_proposal_summary(self, preparation: WorkspaceActionPreparationResult) -> str:
        if not preparation.actions:
            return ""

        parts = [f"{Path(action.targetFile).name}：{action.summary}" for action in preparation.actions[:3]]
        return f"共生成 {len(preparation.actions)} 个待确认变更；" + "；".join(parts)

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
    # 调用底层模型客户端，并统一清理返回文本。
    def _run_model(self, system_prompt: str, user_prompt: str) -> str:
        raw_content = self.ollama.chat(system_prompt=system_prompt, user_prompt=user_prompt)
        return self._sanitize_response(raw_content)

    # 方法说明：
    # 判断当前是否值得触发一次结构化重试。
    def _should_retry_action_plan(self, parsed_actions: list[object], prepared_actions: list[object]) -> bool:
        return not parsed_actions or not prepared_actions

    # 方法说明：
    # 清理模型可能返回的思维链占位文本。
    def _sanitize_response(self, content: str) -> str:
        cleaned = re.sub(r"<think>.*?</think>\s*", "", content, flags=re.DOTALL).strip()
        return cleaned or content.strip()
