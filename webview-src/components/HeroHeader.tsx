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
      <div className="hero-main">
        <div className="avatar-shell compact">
          {avatarUri ? <img className="avatar-image" src={avatarUri} alt="avatar" /> : null}
        </div>
        <div className="hero-copy">
          <h1>Yinlin Assistant</h1>
          <p>当前文件直改与项目级预览共用同一条 Agent 链路。</p>
        </div>
      </div>
      <div className="hero-tags">
        <span className="pill">Current File Edit</span>
        <span className="pill">Project Diff</span>
        <span className="pill">Ollama</span>
      </div>
    </section>
  );
}
