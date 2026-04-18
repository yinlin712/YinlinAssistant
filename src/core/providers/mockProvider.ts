import { AgentContext, AgentResponse, ConversationTurn, ModelProvider } from "../types";

// 文件说明：
// 本文件定义用于界面联调的 Mock 提供者。
// 当后端不可用时，可以用它验证前端面板和消息流是否正常。


// 类说明：
// 生成固定格式的模拟回复，不依赖真实模型。
export class MockModelProvider implements ModelProvider {
  public readonly name = "mock";

  // 方法说明：
  // 根据当前上下文返回一段固定的调试说明。
  public async generate(
    prompt: string,
    context: AgentContext,
    _conversationHistory: ConversationTurn[] = [],
  ): Promise<AgentResponse> {
    const focus = context.selectedText
      ? "检测到选中代码，因此回复会优先围绕该片段展开。"
      : "当前没有选中代码，因此回复将基于活动文件上下文。";

    const fileInfo = context.activeFile
      ? `当前活动文件：${context.activeFile}`
      : "编辑器中当前没有活动文件。";

    const rewriteHint = context.fullDocumentText
      ? "当前文件长度适中，可用于演示文件级改写规划。"
      : "当前文件未提供完整内容，因此改写规划可能会跳过活动文件。";

    const reply = [
      "这是一条用于界面联调的模拟回复。",
      `用户请求：${prompt}`,
      fileInfo,
      focus,
      rewriteHint,
      "如需真实项目规划能力，请切换到 Python 后端模式。",
    ].join("\n");

    return {
      content: reply,
      mood: "helpful",
      actions: [],
      appliedActions: [],
      requiresConfirmation: false,
      autoApplyActions: false,
      proposalSummary: "",
    };
  }
}
