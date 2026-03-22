import { useEffect, useState } from "react";
import { Composer } from "./components/Composer";
import { ChatList } from "./components/ChatList";
import { HeroHeader } from "./components/HeroHeader";
import { ProposalPanel } from "./components/ProposalPanel";
import { QuickActions } from "./components/QuickActions";
import { StatusBar } from "./components/StatusBar";
import { vscode } from "./vscode";
import {
  ChatMessage,
  HydratePayload,
  PendingProposalPayload,
  StatusPayload,
  WebviewIncomingMessage,
} from "./types";

// 文件说明：
// 本文件定义 Webview 顶层页面，负责维护前端状态并处理来自插件端的消息。

// 类型说明：
// 约束顶层组件所需的外部资源参数。
type AppProps = {
  avatarUri?: string;
};

// 组件说明：
// 统一组织头部、状态栏、快捷任务、变更预览、对话区与输入区。
export function App({ avatarUri }: AppProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [status, setStatus] = useState("待命");
  const [provider, setProvider] = useState("local");
  const [activeFile, setActiveFile] = useState("无活动文件");
  const [emptyProposalText, setEmptyProposalText] = useState("当前还没有待确认的变更方案。");
  const [proposal, setProposal] = useState<PendingProposalPayload | null>(null);

  // 方法说明：
  // 监听插件端推送的消息，并同步前端展示状态。
  useEffect(() => {
    function handleMessage(event: MessageEvent<WebviewIncomingMessage>) {
      const message = event.data;

      if (message.type === "hydrate") {
        const payload = message.payload as HydratePayload;
        setMessages(payload.messages);
        setStatus(payload.status);
        setProvider(payload.provider);
        setActiveFile(payload.activeFile || payload.noActiveFile);
        setEmptyProposalText(payload.proposalEmpty);
        setProposal(payload.pendingProposal);
      }

      if (message.type === "message") {
        const payload = message.payload as ChatMessage;
        setMessages((previous) => [...previous, payload]);
      }

      if (message.type === "status") {
        const payload = message.payload as StatusPayload;
        setStatus(payload.status);
        setProvider(payload.provider);
        setActiveFile(payload.activeFile || payload.noActiveFile);
      }

      if (message.type === "proposal") {
        setProposal(message.payload as PendingProposalPayload);
      }

      if (message.type === "clearProposal") {
        const payload = message.payload as { emptyText: string };
        setProposal(null);
        setEmptyProposalText(payload.emptyText);
      }
    }

    window.addEventListener("message", handleMessage);
    return () => window.removeEventListener("message", handleMessage);
  }, []);

  // 方法说明：
  // 将用户输入统一封装为 Webview 消息并发送给插件端。
  function submitPrompt(prompt: string) {
    vscode.postMessage({
      type: "submitPrompt",
      payload: { prompt },
    });
  }

  return (
    <main className="app">
      <HeroHeader avatarUri={avatarUri} />
      <StatusBar status={status} provider={provider} activeFile={activeFile} />

      <section className="workspace-shell">
        <QuickActions onSubmitPrompt={submitPrompt} />
        <ProposalPanel
          proposal={proposal}
          emptyText={emptyProposalText}
          onApply={() => vscode.postMessage({ type: "applyPendingActions" })}
          onDiscard={() => vscode.postMessage({ type: "discardPendingActions" })}
        />
        <ChatList messages={messages} />
      </section>

      <Composer onSubmitPrompt={submitPrompt} />
    </main>
  );
}
