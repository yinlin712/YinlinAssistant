import { FormEvent, useState } from "react";

type ComposerProps = {
  onSubmitPrompt: (prompt: string) => void;
};

export function Composer({ onSubmitPrompt }: ComposerProps) {
  const [value, setValue] = useState("");

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
