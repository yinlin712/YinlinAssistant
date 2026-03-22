import * as path from "path";
import { ActionPreviewItem, AgentAction } from "./types";

const CONTEXT_LINES = 2;
const MAX_DIFF_LINES = 160;

// 生成一个适合在侧边栏中展示的“简化 unified diff”。
// 这不是完整的 git diff 算法，但足够帮助用户先确认本次改动的大致范围。
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

function splitLines(content: string): string[] {
  if (!content) {
    return [];
  }

  return content.replace(/\r\n/g, "\n").replace(/\r/g, "\n").split("\n");
}

function findCommonPrefix(left: string[], right: string[]): number {
  let index = 0;
  while (index < left.length && index < right.length && left[index] === right[index]) {
    index += 1;
  }
  return index;
}

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

function trimDiffLines(lines: string[]): string {
  if (lines.length <= MAX_DIFF_LINES) {
    return lines.join("\n");
  }

  const kept = lines.slice(0, MAX_DIFF_LINES);
  kept.push(`... (${lines.length - MAX_DIFF_LINES} more diff lines omitted)`);
  return kept.join("\n");
}

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

function defaultSummary(kind: AgentAction["kind"]): string {
  if (kind === "create_file") {
    return "新增文件";
  }

  if (kind === "update_documentation") {
    return "更新文档";
  }

  return "修改文件";
}
