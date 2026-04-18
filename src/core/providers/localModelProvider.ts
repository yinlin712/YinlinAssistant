import * as vscode from "vscode";
import { AgentAction, AgentContext, AgentResponse, AgentStreamHandlers, ConversationTurn, ModelProvider } from "../types";

// 文件说明：
// 本文件定义本地 Python 后端提供者。
// 插件端通过它把请求发送给 FastAPI 后端，而不是直接调用 Ollama。

type PythonAgentPayload = {
  content?: string;
  mood?: AgentResponse["mood"];
  actions?: AgentAction[];
  requiresConfirmation?: boolean;
  autoApplyActions?: boolean;
  proposalSummary?: string;
};


// 类说明：
// 负责通过 HTTP 调用本地 Python Agent 服务。
export class LocalModelProvider implements ModelProvider {
  public readonly name = "python-agent";

  // 方法说明：
  // 向后端发送请求，并将返回值转换为插件端统一响应结构。
  public async generate(
    prompt: string,
    context: AgentContext,
    conversationHistory: ConversationTurn[] = [],
  ): Promise<AgentResponse> {
    const config = vscode.workspace.getConfiguration("vibeCodingAgent");
    const endpoint = config.get<string>("localModelEndpoint", "http://127.0.0.1:8000/generate");

    try {
      const response = await fetch(endpoint, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          prompt,
          context,
          conversationHistory,
        }),
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      const payload = await response.json() as PythonAgentPayload;
      return {
        content: payload.content ?? "Python 后端返回了空响应。",
        mood: payload.mood ?? "helpful",
        actions: payload.actions ?? [],
        appliedActions: [],
        requiresConfirmation: payload.requiresConfirmation ?? false,
        autoApplyActions: payload.autoApplyActions ?? false,
        proposalSummary: payload.proposalSummary ?? "",
      };
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      return {
        content: [
          "Python 后端当前不可用。",
          `接口地址：${endpoint}`,
          `错误信息：${message}`,
          "请先启动后端：python -m uvicorn backend.main:app --reload",
        ].join("\n"),
        mood: "idle",
        actions: [],
        appliedActions: [],
        requiresConfirmation: false,
        autoApplyActions: false,
        proposalSummary: "",
      };
    }
  }

  // 方法说明：
  // 通过流式接口接收实时 patch 预览与最终响应结果。
  public async streamGenerate(
    prompt: string,
    context: AgentContext,
    conversationHistory: ConversationTurn[],
    handlers: AgentStreamHandlers,
  ): Promise<AgentResponse> {
    const config = vscode.workspace.getConfiguration("vibeCodingAgent");
    const endpoint = config.get<string>("localModelEndpoint", "http://127.0.0.1:8000/generate");
    const streamEndpoint = endpoint.endsWith("/generate")
      ? `${endpoint.slice(0, -"/generate".length)}/stream-generate`
      : `${endpoint}/stream`;

    try {
      const response = await fetch(streamEndpoint, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          prompt,
          context,
          conversationHistory,
        }),
      });

      if (!response.ok || !response.body) {
        return await this.generate(prompt, context, conversationHistory);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let finalResponse: AgentResponse | undefined;

      while (true) {
        const { value, done } = await reader.read();
        if (done) {
          break;
        }

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";

        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed) {
            continue;
          }

          const event = JSON.parse(trimmed) as {
            type?: string;
            payload?: Record<string, unknown>;
          };

          if (event.type === "status") {
            handlers.onStatus?.(String(event.payload?.status ?? ""));
            continue;
          }

          if (event.type === "message_chunk") {
            handlers.onMessageChunk?.(String(event.payload?.chunk ?? ""));
            continue;
          }

          if (event.type === "patch") {
            handlers.onPatchPreview?.(String(event.payload?.updatedContent ?? ""), context);
            continue;
          }

          if (event.type === "result") {
            const payload = event.payload as PythonAgentPayload | undefined;
            finalResponse = {
              content: payload?.content ?? "Python 后端返回了空响应。",
              mood: payload?.mood ?? "helpful",
              actions: payload?.actions ?? [],
              appliedActions: [],
              requiresConfirmation: payload?.requiresConfirmation ?? false,
              autoApplyActions: payload?.autoApplyActions ?? false,
              proposalSummary: payload?.proposalSummary ?? "",
            };
          }
        }
      }

      if (buffer.trim()) {
        const event = JSON.parse(buffer.trim()) as {
          type?: string;
          payload?: Record<string, unknown>;
        };
        if (event.type === "result") {
          const payload = event.payload as PythonAgentPayload | undefined;
          finalResponse = {
            content: payload?.content ?? "Python 后端返回了空响应。",
            mood: payload?.mood ?? "helpful",
            actions: payload?.actions ?? [],
            appliedActions: [],
            requiresConfirmation: payload?.requiresConfirmation ?? false,
            autoApplyActions: payload?.autoApplyActions ?? false,
            proposalSummary: payload?.proposalSummary ?? "",
          };
        }
      }

      return finalResponse ?? await this.generate(prompt, context, conversationHistory);
    } catch {
      return await this.generate(prompt, context, conversationHistory);
    }
  }
}
