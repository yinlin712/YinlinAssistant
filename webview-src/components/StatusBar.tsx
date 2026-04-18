type StatusBarProps = {
  status: string;
  provider: string;
  activeFile: string;
};

/**
 * 展示当前工作状态与上下文线索。
 */
export function StatusBar({ status, provider, activeFile }: StatusBarProps) {
  return (
    <section className="status-bar">
      <div className="status-main">
        <span className="status-dot" aria-hidden="true" />
        <span className="status-label">{status}</span>
      </div>
      <span className="status-provider">{provider}</span>
      <span className="status-file" title={activeFile}>
        {formatActiveFile(activeFile)}
      </span>
    </section>
  );
}

/**
 * 将长路径压缩为更适合侧边栏展示的形式。
 */
function formatActiveFile(activeFile: string): string {
  const normalized = activeFile.replace(/\\/g, "/");
  const segments = normalized.split("/").filter(Boolean);
  if (segments.length <= 2) {
    return activeFile;
  }

  return `${segments[segments.length - 2]}/${segments[segments.length - 1]}`;
}
