// 文件说明：
// 本文件负责渲染侧边栏顶部概览区域，用于展示助手身份与核心能力标签。

// 类型说明：
// 约束头部组件所需的头像资源参数。
type HeroHeaderProps = {
  avatarUri?: string;
};

// 组件说明：
// 展示助手标题、头像和能力标签。
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
