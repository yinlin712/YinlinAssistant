import { FormEvent, useState } from "react";

// 文件说明：
// 本文件负责渲染输入区，并在提交后将用户需求发送给顶层页面。

// 类型说明：
// 约束输入区组件对外暴露的提交能力。
type ComposerProps = {
  onSubmitPrompt: (prompt: string) => void;
};

// 组件说明：
// 管理当前输入内容并在表单提交时触发消息发送。
export function Composer({ onSubmitPrompt }: ComposerProps) {
  const [value, setValue] = useState("");

  // 方法说明：
  // 拦截表单默认提交行为，并将非空输入发送给上层。
  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const nextValue = value.trim();
    if (!nextValue) {
      return;
    }

    onSubmitPrompt(nextValue);
    setValue("");
  }

  return (
    <form className="composer" onSubmit={handleSubmit}>
      <div className="composer-copy">
        <strong>输入需求</strong>
        <span>先描述你想完成的目标，再决定是否需要生成项目级修改方案。</span>
      </div>
      <div className="composer-main">
        <textarea
          value={value}
          onChange={(event) => setValue(event.target.value)}
          placeholder="例如：请检索当前项目并生成一组待确认的变更方案，包括新增工具文件、修改现有代码和更新 README。"
        />
        <button type="submit">发送</button>
      </div>
    </form>
  );
}
