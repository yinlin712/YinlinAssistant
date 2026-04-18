import { PendingProposalPayload } from "../types";

type ProposalPanelProps = {
  proposal: PendingProposalPayload | null;
  emptyText: string;
  onApply: () => void;
  onDiscard: () => void;
};

/**
 * 展示待确认的文件变更方案与 diff 预览。
 */
export function ProposalPanel({ proposal, emptyText, onApply, onDiscard }: ProposalPanelProps) {
  return (
    <section className={`proposal-panel${proposal ? "" : " is-empty"}`}>
      <div className="proposal-summary">
        <div className="proposal-summary-top">
          <strong>{proposal?.title ?? "待确认变更"}</strong>
          {proposal?.isStreaming ? <span className="proposal-badge">生成中</span> : null}
        </div>
        <span>{proposal?.summary ?? emptyText}</span>
      </div>

      {proposal ? (
        <>
          {proposal.isStreaming ? (
            <div className="proposal-streaming-hint">
              正在根据模型输出持续刷新 patch，待生成完成后才能应用。
            </div>
          ) : (
            <div className="proposal-controls">
              <button className="proposal-button" type="button" onClick={onApply}>
                应用修改
              </button>
              <button className="proposal-button secondary" type="button" onClick={onDiscard}>
                清空预览
              </button>
            </div>
          )}

          <div className="proposal-list">
            {proposal.actions.map((action) => (
              <article className="proposal-card" key={`${action.kind}-${action.targetFile}`}>
                <div className="proposal-card-top">
                  <h3>{action.targetFile}</h3>
                  <span className="proposal-kind">{action.kind}</span>
                </div>
                <pre className="proposal-diff">
                  {action.diffText.split("\n").map((line, index) => (
                    <span className={buildDiffLineClassName(line)} key={`${action.targetFile}-${index}`}>
                      {line}
                    </span>
                  ))}
                </pre>
              </article>
            ))}
          </div>
        </>
      ) : (
        <div className="proposal-empty">
          <span className="proposal-empty-line" />
          <span className="proposal-empty-line short" />
          <span className="proposal-empty-line" />
        </div>
      )}
    </section>
  );
}

/**
 * 根据 diff 行前缀返回用于着色的样式类名。
 */
function buildDiffLineClassName(line: string): string {
  if (line.startsWith("+ ")) {
    return "diff-line diff-added";
  }

  if (line.startsWith("- ")) {
    return "diff-line diff-removed";
  }

  if (line.startsWith("@@")) {
    return "diff-line diff-hunk";
  }

  if (line.startsWith("+++") || line.startsWith("---")) {
    return "diff-line diff-header";
  }

  return "diff-line";
}
