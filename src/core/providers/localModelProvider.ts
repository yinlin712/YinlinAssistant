import * as vscode from "vscode";
import { AgentAction, AgentContext, AgentResponse, ModelProvider } from "../types";

type PythonAgentPayload = {
  content?: string;
  mood?: AgentResponse["mood"];
  actions?: AgentAction[];
  requiresConfirmation?: boolean;
  proposalSummary?: string;
};

export class LocalModelProvider implements ModelProvider {
  public readonly name = "python-agent";

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
        content: payload.content ?? "The Python agent returned an empty response.",
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
          "The Python agent backend is unavailable.",
          `endpoint: ${endpoint}`,
          `error: ${message}`,
          "Start the backend with: python -m uvicorn backend.main:app --reload",
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
