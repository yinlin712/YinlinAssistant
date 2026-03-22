import { PendingProposalPayload } from "../types";

type ProposalPanelProps = {
  proposal: PendingProposalPayload | null;
  emptyText: string;
  onApply: () => void;
  onDiscard: () => void;
};

export function ProposalPanel({ proposal, emptyText, onApply, onDiscard }: ProposalPanelProps) {
  return (
    <section className={`proposal-panel${proposal ? "" : " is-empty"}`}>
      <div className="section-head">
        <h2>{proposal?.title ?? "待确认变更"}</h2>
        <p>{proposal?.summary ?? emptyText}</p>
      </div>

      {proposal ? (
        <>
          <div className="proposal-controls">
            <button className="proposal-button" type="button" onClick={onApply}>
              确认应用
            </button>
            <button className="proposal-button secondary" type="button" onClick={onDiscard}>
              丢弃预览
            </button>
          </div>

          <div className="proposal-list">
            {proposal.actions.map((action) => (
              <article className="proposal-card" key={`${action.kind}-${action.targetFile}`}>
                <div className="proposal-card-top">
                  <span className="proposal-kind">{action.kind}</span>
                  <h3>{action.targetFile}</h3>
                </div>
                <p className="proposal-card-summary">{action.summary}</p>
                <pre className="proposal-diff">{action.diffText}</pre>
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
