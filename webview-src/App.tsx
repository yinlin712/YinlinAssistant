import { useEffect, useState } from "react";
import { Composer } from "./components/Composer";
import { ChatList } from "./components/ChatList";
import { ProposalPanel } from "./components/ProposalPanel";
import { StatusBar } from "./components/StatusBar";
import {
  ChatMessage,
  HydratePayload,
  MessageChunkPayload,
  PendingProposalPayload,
  PersistedWebviewState,
  StatusPayload,
  WebviewIncomingMessage,
} from "./types";
import { vscode } from "./vscode";

const CURRENT_SESSION_ID = document.body.dataset.sessionId ?? "";

const DEFAULT_STATE: PersistedWebviewState = {
  sessionId: CURRENT_SESSION_ID,
  messages: [],
  status: "待命",
  provider: "local",
  activeFile: "无活动文件",
  emptyProposalText: "当前还没有待确认的变更方案。",
  proposal: null,
  streamingAgentContent: "",
};

/**
 * Webview 顶层页面，负责维护状态并处理来自插件端的消息。
 */
export function App() {
  const initialState = readPersistedState();
  const [messages, setMessages] = useState<ChatMessage[]>(initialState.messages);
  const [status, setStatus] = useState(initialState.status);
  const [provider, setProvider] = useState(initialState.provider);
  const [activeFile, setActiveFile] = useState(initialState.activeFile);
  const [emptyProposalText, setEmptyProposalText] = useState(initialState.emptyProposalText);
  const [proposal, setProposal] = useState<PendingProposalPayload | null>(initialState.proposal);
  const [streamingAgentContent, setStreamingAgentContent] = useState(initialState.streamingAgentContent);

  /**
   * 在 Webview 状态变化时持久化到 VS Code 内部状态缓存。
   */
  useEffect(() => {
    const nextState: PersistedWebviewState = {
      sessionId: CURRENT_SESSION_ID,
      messages,
      status,
      provider,
      activeFile,
      emptyProposalText,
      proposal,
      streamingAgentContent,
    };
    vscode.setState(nextState);
  }, [messages, status, provider, activeFile, emptyProposalText, proposal, streamingAgentContent]);

  /**
   * 监听插件端推送的消息，并同步前端显示状态。
   */
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
        setStreamingAgentContent("");
        return;
      }

      if (message.type === "message") {
        const payload = message.payload as ChatMessage;
        if (payload.role === "agent") {
          setStreamingAgentContent("");
        }
        setMessages((previous) => [...previous, payload]);
        return;
      }

      if (message.type === "messageChunk") {
        const payload = message.payload as MessageChunkPayload;
        if (payload.role === "agent") {
          setStreamingAgentContent((previous) => previous + payload.chunk);
        }
        return;
      }

      if (message.type === "status") {
        const payload = message.payload as StatusPayload;
        setStatus(payload.status);
        setProvider(payload.provider);
        setActiveFile(payload.activeFile || payload.noActiveFile);
        return;
      }

      if (message.type === "proposal") {
        setProposal(message.payload as PendingProposalPayload);
        return;
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

  /**
   * 将用户输入统一封装为 Webview 消息并发送给插件端。
   */
  function submitPrompt(prompt: string) {
    vscode.postMessage({
      type: "submitPrompt",
      payload: { prompt },
    });
  }

  return (
    <main className="app">
      <StatusBar status={status} provider={provider} activeFile={activeFile} />
      <ChatList
        messages={messages}
        streamingMessage={streamingAgentContent
          ? {
              role: "agent",
              content: streamingAgentContent,
            }
          : null}
      />
      {proposal ? (
        <ProposalPanel
          proposal={proposal}
          emptyText={emptyProposalText}
          onApply={() => vscode.postMessage({ type: "applyPendingActions" })}
          onDiscard={() => vscode.postMessage({ type: "discardPendingActions" })}
        />
      ) : null}
      <Composer onSubmitPrompt={submitPrompt} />
    </main>
  );
}

/**
 * 读取 VS Code 为当前 Webview 缓存的状态。
 */
function readPersistedState(): PersistedWebviewState {
  const rawState = vscode.getState() as Partial<PersistedWebviewState> | undefined;
  if (!rawState || rawState.sessionId !== CURRENT_SESSION_ID) {
    return DEFAULT_STATE;
  }

  return {
    sessionId: rawState.sessionId ?? DEFAULT_STATE.sessionId,
    messages: rawState.messages ?? DEFAULT_STATE.messages,
    status: rawState.status ?? DEFAULT_STATE.status,
    provider: rawState.provider ?? DEFAULT_STATE.provider,
    activeFile: rawState.activeFile ?? DEFAULT_STATE.activeFile,
    emptyProposalText: rawState.emptyProposalText ?? DEFAULT_STATE.emptyProposalText,
    proposal: rawState.proposal ?? DEFAULT_STATE.proposal,
    streamingAgentContent: rawState.streamingAgentContent ?? DEFAULT_STATE.streamingAgentContent,
  };
}
