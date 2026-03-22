type StatusBarProps = {
  status: string;
  provider: string;
  activeFile: string;
};

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
