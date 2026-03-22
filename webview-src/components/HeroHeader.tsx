type HeroHeaderProps = {
  avatarUri?: string;
};

export function HeroHeader({ avatarUri }: HeroHeaderProps) {
  return (
    <section className="hero">
      <div className="hero-identity">
        <div className="avatar-shell">
          {avatarUri ? <img className="avatar-image" src={avatarUri} alt="avatar" /> : null}
        </div>
        <div className="hero-copy">
          <h1>Vibe Coding Agent</h1>
          <p>面向 VS Code 的项目级编程助手，支持检索工作区、生成变更预览，并在确认后应用修改。</p>
        </div>
      </div>
      <div className="hero-tags">
        <span className="pill">Python Backend</span>
        <span className="pill">Ollama</span>
        <span className="pill">Diff Preview</span>
      </div>
    </section>
  );
}
