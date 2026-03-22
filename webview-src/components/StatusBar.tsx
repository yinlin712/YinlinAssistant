// 文件说明：
// 本文件负责展示当前工作状态、模型来源与活动文件信息。

// 类型说明：
// 约束状态栏组件需要的展示数据。
type StatusBarProps = {
  status: string;
  provider: string;
  activeFile: string;
};

// 组件说明：
// 使用紧凑卡片展示当前交互上下文。
export function StatusBar({ status, provider, activeFile }: StatusBarProps) {
  return (
    <section className="status-bar">
      <div className="status-card">
        <span>状态</span>
        <strong>{status}</strong>
      </div>
      <div className="status-card">
        <span>模型</span>
        <strong>{provider}</strong>
      </div>
      <div className="status-card file-card">
        <span>当前文件</span>
        <strong>{activeFile}</strong>
      </div>
    </section>
  );
}
