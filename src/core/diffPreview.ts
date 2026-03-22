import * as path from "path";
import { ActionPreviewItem, AgentAction } from "./types";

// 文件说明：
// 本文件负责将结构化动作转换为适合侧边栏展示的简化 diff 文本。

const CONTEXT_LINES = 2;
const MAX_DIFF_LINES = 160;


// 函数说明：
// 将动作列表转换为预览列表。
export function buildActionPreviewItems(
  actions: AgentAction[],
  workspaceRoot?: string
): ActionPreviewItem[] {
  return actions.map((action) => ({
    kind: action.kind,
    targetFile: toDisplayPath(action.targetFile, workspaceRoot),
    summary: action.summary || defaultSummary(action.kind),
    diffText: buildUnifiedDiff(action),
  }));
}


// 函数说明：
// 为单个动作生成简化版 unified diff。
function buildUnifiedDiff(action: AgentAction): string {
  const oldLines = splitLines(action.originalContent);
  const newLines = splitLines(action.updatedContent);
  const header = [
    `--- ${action.kind === "create_file" ? "(new file)" : action.targetFile}`,
    `+++ ${action.targetFile}`,
  ];

  if (oldLines.length === 0 && newLines.length > 0) {
    return trimDiffLines([...header, "@@ new file @@", ...newLines.map((line) => `+ ${line}`)]);
  }

  const prefixLength = findCommonPrefix(oldLines, newLines);
  const suffixLength = findCommonSuffix(oldLines, newLines, prefixLength);
  const oldChanged = oldLines.slice(prefixLength, oldLines.length - suffixLength);
  const newChanged = newLines.slice(prefixLength, newLines.length - suffixLength);

  if (oldChanged.length === 0 && newChanged.length === 0) {
    return [...header, "@@ no changes @@"].join("\n");
  }

  const startContext = Math.max(0, prefixLength - CONTEXT_LINES);
  const endContext = Math.min(oldLines.length, oldLines.length - suffixLength + CONTEXT_LINES);
  const beforeContext = oldLines.slice(startContext, prefixLength);
  const afterContext = oldLines.slice(oldLines.length - suffixLength, endContext);

  const diffLines = [
    ...header,
    `@@ around line ${prefixLength + 1} @@`,
    ...beforeContext.map((line) => `  ${line}`),
    ...oldChanged.map((line) => `- ${line}`),
    ...newChanged.map((line) => `+ ${line}`),
    ...afterContext.map((line) => `  ${line}`),
  ];

  return trimDiffLines(diffLines);
}


// 函数说明：
// 将文本内容拆分为逐行数组。
function splitLines(content: string): string[] {
  if (!content) {
    return [];
  }

  return content.replace(/\r\n/g, "\n").replace(/\r/g, "\n").split("\n");
}


// 函数说明：
// 计算新旧文本的公共前缀长度。
function findCommonPrefix(left: string[], right: string[]): number {
  let index = 0;
  while (index < left.length && index < right.length && left[index] === right[index]) {
    index += 1;
  }
  return index;
}


// 函数说明：
// 计算新旧文本的公共后缀长度。
function findCommonSuffix(left: string[], right: string[], prefixLength: number): number {
  let index = 0;

  while (
    index < left.length - prefixLength &&
    index < right.length - prefixLength &&
    left[left.length - 1 - index] === right[right.length - 1 - index]
  ) {
    index += 1;
  }

  return index;
}


// 函数说明：
// 控制侧边栏中单个 diff 的最大显示行数。
function trimDiffLines(lines: string[]): string {
  if (lines.length <= MAX_DIFF_LINES) {
    return lines.join("\n");
  }

  const kept = lines.slice(0, MAX_DIFF_LINES);
  kept.push(`... (${lines.length - MAX_DIFF_LINES} more diff lines omitted)`);
  return kept.join("\n");
}


// 函数说明：
// 将绝对路径转换为相对工作区路径，便于界面展示。
function toDisplayPath(targetFile: string, workspaceRoot?: string): string {
  if (!workspaceRoot) {
    return targetFile;
  }

  const relative = path.relative(workspaceRoot, targetFile);
  if (!relative.startsWith("..") && relative !== "") {
    return relative;
  }

  return targetFile;
}


// 函数说明：
// 为缺省动作摘要提供简要文本。
function defaultSummary(kind: AgentAction["kind"]): string {
  if (kind === "create_file") {
    return "新增文件";
  }

  if (kind === "update_documentation") {
    return "更新文档";
  }

  return "修改文件";
}
