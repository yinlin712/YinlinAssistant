import { FormEvent, KeyboardEvent, useState } from "react";

type ComposerProps = {
  onSubmitPrompt: (prompt: string) => void;
};

/**
 * 管理输入内容，并向上层发起提交。
 */
export function Composer({ onSubmitPrompt }: ComposerProps) {
  const [value, setValue] = useState("");

  /**
   * 提交当前输入框中的请求。
   */
  function submitCurrentValue() {
    const nextValue = value.trim();
    if (!nextValue) {
      return;
    }

    onSubmitPrompt(nextValue);
    setValue("");
  }

  /**
   * 拦截表单默认提交行为。
   */
  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    submitCurrentValue();
  }

  /**
   * 支持 Enter 直接发送，Shift + Enter 换行。
   */
  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submitCurrentValue();
    }
  }

  return (
    <form className="composer" onSubmit={handleSubmit}>
      <div className="composer-input">
        <textarea
          value={value}
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="输入需求，例如：解释这个函数；帮我继续封装这个函数；请检索整个项目并规划一组多文件修改。"
        />
        <div className="composer-hint">Enter 发送，Shift + Enter 换行</div>
      </div>
      <button type="submit">发送</button>
    </form>
  );
}
