import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

// 文件说明：
// 本文件负责将助手返回的 Markdown 文本渲染为结构化 HTML。

// 类型说明：
// 约束 Markdown 渲染组件的输入参数。
type MarkdownContentProps = {
  content: string;
};

// 组件说明：
// 以安全方式渲染 Markdown，并支持常见的 GitHub Flavored Markdown 语法。
export function MarkdownContent({ content }: MarkdownContentProps) {
  return (
    <ReactMarkdown
      className="markdown-body"
      remarkPlugins={[remarkGfm]}
      linkTarget="_blank"
    >
      {content}
    </ReactMarkdown>
  );
}
