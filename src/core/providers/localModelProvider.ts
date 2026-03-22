import * as vscode from "vscode";
import { AgentAction, AgentContext, AgentResponse, ModelProvider } from "../types";

// 文件说明：
// 本文件定义本地 Python 后端提供者。
// 插件端通过它把请求发送给 FastAPI 后端，而不是直接调用 Ollama。

type PythonAgentPayload = {
  content?: string;
  mood?: AgentResponse["mood"];
  actions?: AgentAction[];
  requiresConfirmation?: boolean;
  proposalSummary?: string;
};


// 类说明：
// 负责通过 HTTP 调用本地 Python Agent 服务。
export class LocalModelProvider implements ModelProvider {
  public readonly name = "python-agent";

  // 方法说明：
  // 向后端发送请求，并将返回值转换为插件端统一响应结构。
  public async generate(prompt: string, context: AgentContext): Promise<AgentResponse> {
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
        proposalSummary: "",
      };
    }
  }
}
