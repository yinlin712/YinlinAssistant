import re

from backend.agent_workflow import AgentWorkflow
from backend.models import GenerateRequest, GenerateResponse
from backend.ollama_client import OllamaClient
from backend.prompt_builder import (
    build_system_prompt,
    build_user_prompt,
    build_workspace_action_prompt,
    build_workspace_action_repair_prompt,
)
from backend.request_classifier import should_propose_workspace_changes
from backend.structured_response import parse_action_plan_response

"""
后端核心 Service。

这一版的职责很明确：
1. 普通提问时返回文字说明
2. 涉及项目修改时，先生成“待确认的多文件变更方案”
3. 变更真正落盘由 VS Code 插件端执行
"""


class CodingAgentService:
    def __init__(self) -> None:
        self.ollama = OllamaClient()
        self.workflow = AgentWorkflow()

    def generate(self, request: GenerateRequest) -> GenerateResponse:
        current_notes = self.workflow.inspect_current_context(request.context)

        if should_propose_workspace_changes(request.prompt):
            return self._generate_workspace_action_proposal(request, current_notes)

        return self._generate_chat_response(request, current_notes)

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
                    content = repaired_content
                    parsed = repaired_parsed
                    preparation = repaired_preparation
            except Exception:
                # 第二次“结构化修复”失败时，仍然保留第一次结果，避免整个请求直接报错。
                pass

        reply = parsed.assistant_reply or "我已经完成项目检索，并生成了一组待确认的文件变更方案。"
        proposal_summary = parsed.proposal_summary or f"共生成 {len(preparation.actions)} 个待确认变更。"

        if preparation.notes:
            note_text = "\n".join(f"- {note}" for note in preparation.notes)
            reply = f"{reply}\n\n补充说明：\n{note_text}"

        if not preparation.actions:
            if "未能解析" not in reply and not parsed.actions:
                reply = (
                    f"{reply}\n\n"
                    "这次我没有提取到可执行的结构化文件动作，所以暂时无法生成 diff 预览。"
                )
            return GenerateResponse(content=reply, mood="helpful")

        return GenerateResponse(
            content=reply,
            mood="helpful",
            actions=preparation.actions,
            requiresConfirmation=True,
            proposalSummary=proposal_summary,
        )

    def _run_model(self, system_prompt: str, user_prompt: str) -> str:
        raw_content = self.ollama.chat(system_prompt=system_prompt, user_prompt=user_prompt)
        return self._sanitize_response(raw_content)

    def _should_retry_action_plan(self, parsed_actions: list[object], prepared_actions: list[object]) -> bool:
        return not parsed_actions or not prepared_actions

    def _sanitize_response(self, content: str) -> str:
        """去掉 deepseek-r1 等模型可能返回的 <think> 推理块。"""
        cleaned = re.sub(r"<think>.*?</think>\s*", "", content, flags=re.DOTALL).strip()
        return cleaned or content.strip()
