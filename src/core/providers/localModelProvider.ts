import * as vscode from "vscode";
import {
  AgentAction,
  AgentContext,
  AgentResponse,
  AgentStreamHandlers,
  ContextSelection,
  ConversationTurn,
  ModelProvider,
  RiskOverview,
  TestAnalysisResult,
  TestExecutionResult,
  TestPlan,
} from "../types";

type PythonAgentPayload = {
  content?: string;
  mood?: AgentResponse["mood"];
  actions?: AgentAction[];
  requiresConfirmation?: boolean;
  autoApplyActions?: boolean;
  proposalSummary?: string;
  riskOverview?: RiskOverview;
  testPlan?: TestPlan;
  contextSelection?: ContextSelection;
};

type TestAnalysisPayload = {
  content?: string;
  summary?: string;
  overallStatus?: TestAnalysisResult["overallStatus"];
};

// 文件说明：
// 本文件定义本地 Python 后端提供者。
// 插件端通过它把请求发送给 FastAPI 后端，而不是直接调用 Ollama。
export class LocalModelProvider implements ModelProvider {
  public readonly name = "python-agent";

  public async generate(
    prompt: string,
    context: AgentContext,
    conversationHistory: ConversationTurn[] = [],
  ): Promise<AgentResponse> {
    const endpoint = this.resolveGenerateEndpoint();

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
      return this.toAgentResponse(payload);
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

  public async streamGenerate(
    prompt: string,
    context: AgentContext,
    conversationHistory: ConversationTurn[],
    handlers: AgentStreamHandlers,
  ): Promise<AgentResponse> {
    const streamEndpoint = this.resolveStreamEndpoint();

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
            finalResponse = this.toAgentResponse(event.payload as PythonAgentPayload | undefined);
          }
        }
      }

      if (buffer.trim()) {
        const event = JSON.parse(buffer.trim()) as {
          type?: string;
          payload?: Record<string, unknown>;
        };
        if (event.type === "result") {
          finalResponse = this.toAgentResponse(event.payload as PythonAgentPayload | undefined);
        }
      }

      return finalResponse ?? await this.generate(prompt, context, conversationHistory);
    } catch {
      return await this.generate(prompt, context, conversationHistory);
    }
  }

  public async analyzeTestReport(
    prompt: string,
    context: AgentContext,
    modifiedFiles: string[],
    executions: TestExecutionResult[],
  ): Promise<TestAnalysisResult> {
    const endpoint = this.resolveTestAnalysisEndpoint();

    try {
      const response = await fetch(endpoint, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          prompt,
          context,
          modifiedFiles,
          executions: executions.map((item) => ({
            command: item.command,
            purpose: item.purpose,
            kind: item.kind,
            confidence: item.confidence,
            exitCode: item.exitCode,
            durationMs: item.durationMs,
            stdout: item.stdout,
            stderr: item.stderr,
          })),
        }),
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      const payload = await response.json() as TestAnalysisPayload;
      return {
        content: payload.content ?? "测试结果分析接口返回了空内容。",
        summary: payload.summary ?? "",
        overallStatus: payload.overallStatus ?? "unknown",
      };
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      return {
        content: `测试结果分析失败：${message}`,
        summary: "测试结果分析失败。",
        overallStatus: "unknown",
      };
    }
  }

  private toAgentResponse(payload?: PythonAgentPayload): AgentResponse {
    return {
      content: payload?.content ?? "Python 后端返回了空响应。",
      mood: payload?.mood ?? "helpful",
      actions: payload?.actions ?? [],
      appliedActions: [],
      requiresConfirmation: payload?.requiresConfirmation ?? false,
      autoApplyActions: payload?.autoApplyActions ?? false,
      proposalSummary: payload?.proposalSummary ?? "",
      riskOverview: payload?.riskOverview,
      testPlan: payload?.testPlan,
      contextSelection: payload?.contextSelection,
    };
  }

  private resolveGenerateEndpoint(): string {
    const config = vscode.workspace.getConfiguration("vibeCodingAgent");
    return config.get<string>("localModelEndpoint", "http://127.0.0.1:8000/generate");
  }

  private resolveStreamEndpoint(): string {
    const endpoint = this.resolveGenerateEndpoint();
    return endpoint.endsWith("/generate")
      ? `${endpoint.slice(0, -"/generate".length)}/stream-generate`
      : `${endpoint}/stream`;
  }

  private resolveTestAnalysisEndpoint(): string {
    const endpoint = this.resolveGenerateEndpoint();
    return endpoint.endsWith("/generate")
      ? `${endpoint.slice(0, -"/generate".length)}/analyze-test-report`
      : `${endpoint}/analyze-test-report`;
  }
}
