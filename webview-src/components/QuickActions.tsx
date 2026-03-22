// 文件说明：
// 本文件集中定义侧边栏快捷任务，并提供当前文件与项目级操作入口。

// 常量说明：
// 定义围绕当前文件的快捷分析任务。
const PRIMARY_ACTIONS = [
  {
    label: "分析当前文件",
    prompt: "请分析当前文件的作用、关键结构、潜在问题，并给出可执行的改进建议。",
  },
  {
    label: "解释选中代码",
    prompt: "请重点解释我当前选中的代码，并说明它在整个文件中的作用。",
  },
  {
    label: "优化建议",
    prompt: "请从初学者角度审查当前文件，指出命名、结构、异常处理和可维护性方面的优化点。",
  },
];

// 常量说明：
// 定义会触发项目检索与结构化改动规划的快捷任务。
const PROJECT_ACTIONS = [
  {
    label: "规划项目修改",
    prompt:
      "请先检索当前项目相关文件，再规划一组待确认的项目级修改方案，必要时可以同时包含新增文件、修改旧文件和更新文档。",
    emphasis: true,
  },
  {
    label: "更新项目文档",
    prompt:
      "请先检索当前项目中与功能说明相关的文件，并规划一组待确认的文档更新方案，优先考虑 README.md 和 docs 目录。",
    emphasis: false,
  },
];

// 类型说明：
// 约束快捷任务组件对外暴露的提交能力。
type QuickActionsProps = {
  onSubmitPrompt: (prompt: string) => void;
};

// 组件说明：
// 以按钮形式展示常用任务，并将预置提示词发送给上层。
export function QuickActions({ onSubmitPrompt }: QuickActionsProps) {
  return (
    <section className="action-panel">
      <div className="section-head">
        <h2>快捷任务</h2>
        <p>先从当前文件出发，再决定是否扩展到整个项目。</p>
      </div>

      <div className="action-group">
        <span className="action-group-label">当前文件</span>
        <div className="quick-actions compact">
          {PRIMARY_ACTIONS.map((action) => (
            <button
              key={action.label}
              className="quick-action"
              type="button"
              onClick={() => onSubmitPrompt(action.prompt)}
            >
              {action.label}
            </button>
          ))}
        </div>
      </div>

      <div className="action-group">
        <span className="action-group-label">项目级操作</span>
        <div className="quick-actions">
          {PROJECT_ACTIONS.map((action) => (
            <button
              key={action.label}
              className={`quick-action${action.emphasis ? " emphasis" : ""}`}
              type="button"
              onClick={() => onSubmitPrompt(action.prompt)}
            >
              {action.label}
            </button>
          ))}
        </div>
      </div>
    </section>
  );
}
