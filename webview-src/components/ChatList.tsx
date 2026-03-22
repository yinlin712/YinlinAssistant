import { ChatMessage } from "../types";

type ChatListProps = {
  messages: ChatMessage[];
};

export function ChatList({ messages }: ChatListProps) {
  return (
    <section className="chat-panel">
      <div className="section-head">
        <h2>对话记录</h2>
        <p>这里会展示分析结果、修改说明和应用反馈。</p>
      </div>
      <div className="chat">
        {messages.map((message, index) => (
          <div className={`message ${message.role}`} key={`${message.role}-${index}`}>
            {message.content}
          </div>
        ))}
      </div>
    </section>
  );
}
