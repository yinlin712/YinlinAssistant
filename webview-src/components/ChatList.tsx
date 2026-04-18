import { useEffect, useRef } from "react";
import { ChatMessage } from "../types";
import { MarkdownContent } from "./MarkdownContent";

type ChatListProps = {
  messages: ChatMessage[];
  streamingMessage?: ChatMessage | null;
};

/**
 * 渲染对话区内容，并在新消息到来时自动滚动到底部。
 */
export function ChatList({ messages, streamingMessage = null }: ChatListProps) {
  const bottomRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [messages, streamingMessage]);

  return (
    <section className="chat-panel">
      <div className="chat">
        {messages.map((message, index) => {
          const previousRole = index > 0 ? messages[index - 1].role : null;
          const isContinuation = previousRole === message.role;

          return (
            <div
              className={`message ${message.role}${isContinuation ? " is-continuation" : ""}`}
              key={`${message.role}-${index}`}
            >
              {!isContinuation ? (
                <div className="message-role">{buildRoleLabel(message.role)}</div>
              ) : null}
              <MarkdownContent content={message.content} />
            </div>
          );
        })}
        {streamingMessage ? (
          <div
            className={`message ${streamingMessage.role} streaming${messages[messages.length - 1]?.role === streamingMessage.role ? " is-continuation" : ""}`}
            key="streaming-agent-message"
          >
            {messages[messages.length - 1]?.role !== streamingMessage.role ? (
              <div className="message-role">{buildRoleLabel(streamingMessage.role)}</div>
            ) : null}
            <MarkdownContent content={streamingMessage.content} />
          </div>
        ) : null}
        <div ref={bottomRef} />
      </div>
    </section>
  );
}

/**
 * 将角色标识映射为界面标签。
 */
function buildRoleLabel(role: ChatMessage["role"]): string {
  if (role === "user") {
    return "你";
  }

  if (role === "system") {
    return "系统";
  }

  return "Code Agent";
}
