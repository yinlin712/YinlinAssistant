import { ChildProcess } from "child_process";
import { spawn } from "child_process";
import * as fs from "fs";
import * as path from "path";
import * as vscode from "vscode";

interface VoiceServiceRuntimeConfig {
  enabled: boolean;
  autoStart: boolean;
  serviceRoot?: string;
  startCommand: string;
  healthUrl: string;
}

/**
 * 在扩展侧托管 AIRI 兼容语音服务的生命周期。
 * 当项目启动后，如果本地语音服务尚未运行，则自动尝试拉起。
 */
export class VoiceServiceManager implements vscode.Disposable {
  private readonly outputChannel = vscode.window.createOutputChannel("Code Agent Voice Service");
  private childProcess?: ChildProcess;
  private startupPromise?: Promise<void>;
  private disposed = false;

  constructor(private readonly extensionUri: vscode.Uri) {}

  /**
   * 确保 AIRI 兼容语音服务处于可用状态。
   */
  public async ensureRunning(): Promise<void> {
    const config = this.readRuntimeConfig();
    if (!config.enabled || !config.autoStart) {
      return;
    }

    if (await this.isHealthy(config.healthUrl)) {
      return;
    }

    if (this.startupPromise) {
      return this.startupPromise;
    }

    this.startupPromise = this.startService(config).finally(() => {
      this.startupPromise = undefined;
    });

    return this.startupPromise;
  }

  public dispose(): void {
    this.disposed = true;
    this.outputChannel.dispose();

    if (this.childProcess && !this.childProcess.killed) {
      this.childProcess.kill();
    }
  }

  private readRuntimeConfig(): VoiceServiceRuntimeConfig {
    const config = vscode.workspace.getConfiguration("vibeCodingAgent");
    const configuredBaseUrl = config.get<string>("voiceApiBaseUrl", "http://127.0.0.1:3000").trim();
    const explicitServiceRoot = config.get<string>("voiceServicePath", "").trim();
    const autoStart = config.get<boolean>("autoStartVoiceService", true);
    const enabled = config.get<boolean>("enableVoiceInteraction", true);
    const startCommand = config.get<string>("voiceServiceStartCommand", "pnpm dev:server").trim() || "pnpm dev:server";

    return {
      enabled,
      autoStart,
      serviceRoot: this.resolveServiceRoot(explicitServiceRoot),
      startCommand,
      healthUrl: `${this.resolveVoiceServiceBaseUrl(configuredBaseUrl)}/health`,
    };
  }

  private resolveServiceRoot(explicitServiceRoot: string): string | undefined {
    if (explicitServiceRoot) {
      return explicitServiceRoot;
    }

    const bundledAiri = path.join(this.extensionUri.fsPath, "airi");
    if (fs.existsSync(path.join(bundledAiri, "package.json"))) {
      return bundledAiri;
    }

    const workspaceRoot = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
    if (!workspaceRoot) {
      return undefined;
    }

    const siblingAiri = path.join(workspaceRoot, "..", "airi");
    if (fs.existsSync(path.join(siblingAiri, "package.json"))) {
      return siblingAiri;
    }

    return undefined;
  }

  private resolveVoiceServiceBaseUrl(configuredBaseUrl: string): string {
    const normalized = configuredBaseUrl.replace(/\/+$/, "");
    if (normalized.endsWith("/api/v1/openai")) {
      return normalized.slice(0, -"/api/v1/openai".length);
    }

    if (normalized.endsWith("/v1")) {
      return normalized.slice(0, -"/v1".length);
    }

    return normalized;
  }

  private async startService(config: VoiceServiceRuntimeConfig): Promise<void> {
    if (!config.serviceRoot) {
      void vscode.window.showWarningMessage(
        "Code Agent 未找到可自动启动的 AIRI 语音服务目录。请检查 airi 仓库是否位于项目根目录，或在设置中配置 voiceServicePath。",
      );
      return;
    }

    this.outputChannel.appendLine(`[Code Agent] Preparing voice service at ${config.serviceRoot}`);

    if (!fs.existsSync(path.join(config.serviceRoot, "pnpm-lock.yaml"))) {
      this.outputChannel.appendLine("[Code Agent] pnpm-lock.yaml not found. Voice service start skipped.");
      return;
    }

    this.childProcess = spawn(config.startCommand, {
      cwd: config.serviceRoot,
      shell: true,
      env: process.env,
      windowsHide: true,
    });

    this.childProcess.stdout?.on("data", (chunk: Buffer) => {
      this.outputChannel.append(chunk.toString());
    });

    this.childProcess.stderr?.on("data", (chunk: Buffer) => {
      this.outputChannel.append(chunk.toString());
    });

    this.childProcess.on("exit", (code) => {
      this.outputChannel.appendLine(`[Code Agent] Voice service exited with code ${code ?? "unknown"}.`);
      this.childProcess = undefined;
    });

    const becameHealthy = await this.waitForHealthy(config.healthUrl, 45000);
    if (!becameHealthy) {
      void vscode.window.showWarningMessage(
        "Code Agent 已尝试自动启动语音服务，但在预期时间内没有检测到健康响应。请检查 AIRI 服务日志输出。",
      );
      this.outputChannel.show(true);
      return;
    }

    this.outputChannel.appendLine("[Code Agent] Voice service is ready.");
  }

  private async waitForHealthy(url: string, timeoutMs: number): Promise<boolean> {
    const startedAt = Date.now();
    while (!this.disposed && Date.now() - startedAt < timeoutMs) {
      if (await this.isHealthy(url)) {
        return true;
      }

      await new Promise((resolve) => setTimeout(resolve, 1500));
    }

    return false;
  }

  private async isHealthy(url: string): Promise<boolean> {
    try {
      const response = await fetch(url, {
        method: "GET",
      });

      return response.ok;
    } catch {
      return false;
    }
  }
}
