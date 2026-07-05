import { spawn } from "child_process";
import * as vscode from "vscode";
import { AgentContext, TestExecutionResult, TestPlan } from "./types";

const OUTPUT_LIMIT = 12000;
const DEFAULT_TIMEOUT_MS = 120000;

// 文件说明：
// 本文件负责在插件端执行修改后的自动测试与验证命令。
// 当前实现以串行方式运行命令，重点保证演示稳定性与结果可解释性。
export class CodeAgentTestRunner {
  public async run(plan: TestPlan, context: AgentContext): Promise<TestExecutionResult[]> {
    if (!plan.available || plan.commands.length === 0 || !context.workspaceRoot) {
      return [];
    }

    const results: TestExecutionResult[] = [];
    for (const command of plan.commands) {
      results.push(await this.runSingleCommand(command, context));
    }

    return results;
  }

  private async runSingleCommand(
    command: TestPlan["commands"][number],
    context: AgentContext,
  ): Promise<TestExecutionResult> {
    const cwd = context.workspaceRoot ?? context.activeFile ?? process.cwd();
    const resolvedCommand = this.resolveCommand(command.command);
    const startedAt = Date.now();

    return new Promise<TestExecutionResult>((resolve) => {
      const child = spawn(resolvedCommand, {
        cwd,
        shell: true,
        env: process.env,
      });

      let stdout = "";
      let stderr = "";
      let settled = false;

      const finalize = (exitCode: number, timedOut: boolean = false) => {
        if (settled) {
          return;
        }
        settled = true;
        const durationMs = Date.now() - startedAt;
        resolve({
          command: resolvedCommand,
          purpose: command.purpose,
          kind: command.kind,
          confidence: command.confidence,
          exitCode,
          durationMs,
          stdout: this.limitOutput(stdout),
          stderr: this.limitOutput(timedOut ? `${stderr}\n[timeout] command exceeded ${DEFAULT_TIMEOUT_MS} ms` : stderr),
          passed: exitCode === 0 && !timedOut,
        });
      };

      const timer = setTimeout(() => {
        child.kill();
        finalize(-1, true);
      }, DEFAULT_TIMEOUT_MS);

      child.stdout.on("data", (chunk) => {
        stdout += String(chunk);
      });

      child.stderr.on("data", (chunk) => {
        stderr += String(chunk);
      });

      child.on("error", (error) => {
        clearTimeout(timer);
        stderr += String(error);
        finalize(-1);
      });

      child.on("close", (code) => {
        clearTimeout(timer);
        finalize(code ?? -1);
      });
    });
  }

  private resolveCommand(command: string): string {
    const trimmed = command.trim();
    const interpreterPath = vscode.workspace
      .getConfiguration("python")
      .get<string>("defaultInterpreterPath", "")
      .trim();

    if (!interpreterPath) {
      return trimmed;
    }

    if (trimmed === "python") {
      return `"${interpreterPath}"`;
    }

    if (trimmed.startsWith("python ")) {
      return `"${interpreterPath}" ${trimmed.slice("python ".length)}`;
    }

    return trimmed;
  }

  private limitOutput(content: string): string {
    if (content.length <= OUTPUT_LIMIT) {
      return content;
    }

    const head = content.slice(0, OUTPUT_LIMIT / 2);
    const tail = content.slice(-OUTPUT_LIMIT / 2);
    return `${head}\n...[truncated]...\n${tail}`;
  }
}
