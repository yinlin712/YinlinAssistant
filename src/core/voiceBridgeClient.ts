import * as vscode from "vscode";

export interface VoiceBridgeConfigPayload {
  baseUrl: string;
  apiKey?: string;
  model: string;
  language?: string;
  sampleRate?: number;
  channels?: number;
}

interface VoiceBridgeStartResponsePayload {
  sessionId: string;
  status: "listening" | "transcribing" | "ready" | "error";
  message: string;
}

interface VoiceBridgeTranscriptResponsePayload {
  sessionId: string;
  status: "listening" | "transcribing" | "ready" | "error";
  text: string;
  message: string;
}

/**
 * 统一封装插件端与本地 Python 录音桥接接口的通信。
 */
export class LocalVoiceBridgeClient {
  public async startRecording(config: VoiceBridgeConfigPayload): Promise<VoiceBridgeStartResponsePayload> {
    return this.requestJson<VoiceBridgeStartResponsePayload>("/voice-bridge/start", {
      method: "POST",
      body: JSON.stringify({
        baseUrl: config.baseUrl,
        apiKey: config.apiKey,
        model: config.model,
        language: config.language,
        sampleRate: config.sampleRate ?? 16000,
        channels: config.channels ?? 1,
      }),
    });
  }

  public async getInterimTranscript(sessionId: string): Promise<VoiceBridgeTranscriptResponsePayload> {
    return this.requestJson<VoiceBridgeTranscriptResponsePayload>(
      `/voice-bridge/${encodeURIComponent(sessionId)}/interim`,
      { method: "GET" },
    );
  }

  public async stopRecording(sessionId: string): Promise<VoiceBridgeTranscriptResponsePayload> {
    return this.requestJson<VoiceBridgeTranscriptResponsePayload>(
      `/voice-bridge/${encodeURIComponent(sessionId)}/stop`,
      { method: "POST" },
    );
  }

  private async requestJson<T>(relativePath: string, init: RequestInit): Promise<T> {
    const endpoint = `${this.resolveBackendBaseUrl()}${relativePath}`;
    const response = await fetch(endpoint, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...(init.headers ?? {}),
      },
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status} ${response.statusText}`);
    }

    return response.json() as Promise<T>;
  }

  private resolveBackendBaseUrl(): string {
    const config = vscode.workspace.getConfiguration("vibeCodingAgent");
    const endpoint = config.get<string>("localModelEndpoint", "http://127.0.0.1:8000/generate");
    return endpoint.endsWith("/generate")
      ? endpoint.slice(0, -"/generate".length)
      : endpoint.replace(/\/+$/, "");
  }
}
