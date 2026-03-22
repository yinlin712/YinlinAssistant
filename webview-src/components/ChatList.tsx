import { ChatMessage } from "../types";

// 文件说明：
// 本文件负责渲染助手对话区，展示用户消息、模型回复与系统执行结果。

// 类型说明：
// 约束对话区组件所需的输入参数。
type ChatListProps = {
  messages: ChatMessage[];
};

// 组件说明：
// 按时间顺序渲染当前会话中的全部消息。
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
