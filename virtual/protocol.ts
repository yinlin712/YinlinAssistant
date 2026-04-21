export type AvatarRuntimeMode = "prototype" | "vrm" | "airi-ready";
export type AvatarExpression = "idle" | "thinking" | "speaking" | "acting";

export const CODE_AGENT_AVATAR_STATE_EVENT = "code-agent:avatar-state";
export const CODE_AGENT_AVATAR_HOST_READY_EVENT = "code-agent:avatar-host-ready";

export interface AvatarRuntimeSnapshot {
  source: "code-agent";
  version: 1;
  avatarMode: AvatarRuntimeMode;
  provider: string;
  status: string;
  expression: AvatarExpression;
  activeFile: string;
  latestAgentMessage: string;
  latestUserMessage: string;
  isStreaming: boolean;
  runtimeHostId: string;
  emittedAt: string;
}

export interface AvatarHostReadyPayload {
  hostId: string;
}
