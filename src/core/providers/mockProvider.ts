import { AgentContext, AgentResponse, ModelProvider } from "../types";

export class MockModelProvider implements ModelProvider {
  public readonly name = "mock";

  public async generate(prompt: string, context: AgentContext): Promise<AgentResponse> {
    const focus = context.selectedText
      ? "Selected code was detected, so the reply can focus on that snippet first."
      : "No code is selected, so the reply is based on the active file context.";

    const fileInfo = context.activeFile
      ? `Active file: ${context.activeFile}`
      : "There is no active file in the editor.";

    const rewriteHint = context.fullDocumentText
      ? "The current file is small enough to support planning a file rewrite."
      : "The current file was not sent as a full document, so rewrite planning may skip the active file.";

    const reply = [
      "This is a mock response used for UI testing.",
      `User request: ${prompt}`,
      fileInfo,
      focus,
      rewriteHint,
      "You can now switch to the Python backend for real Ollama-powered project planning.",
    ].join("\n");

    return {
      content: reply,
      mood: "helpful",
      actions: [],
      appliedActions: [],
      requiresConfirmation: false,
      proposalSummary: "",
    };
  }
}
