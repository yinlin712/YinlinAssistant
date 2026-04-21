import { reactive } from "vue";
import type { AvatarConfig } from "../webview-src/types";
import type { AvatarExpression, AvatarHostReadyPayload, AvatarRuntimeSnapshot } from "./protocol";
import {
  CODE_AGENT_AVATAR_HOST_READY_EVENT,
  CODE_AGENT_AVATAR_STATE_EVENT,
} from "./protocol";

export interface AvatarBridgeState extends AvatarRuntimeSnapshot {
  hostReady: boolean;
}

interface SyncBridgeOptions {
  status: string;
  provider: string;
  activeFile: string;
  latestAgentMessage: string;
  latestUserMessage: string;
  isStreaming: boolean;
}

/**
 * 创建 Webview 中的数字人状态桥。
 */
export function createAvatarBridge(avatar: AvatarConfig) {
  const runtimeHostId = `code-agent-avatar-host-${Date.now().toString(36)}`;
  const state = reactive<AvatarBridgeState>({
    source: "code-agent",
    version: 1,
    avatarMode: avatar.mode,
    provider: "local",
    status: "待命",
    expression: "idle",
    activeFile: "无活动文件",
    latestAgentMessage: "",
    latestUserMessage: "",
    isStreaming: false,
    runtimeHostId,
    emittedAt: new Date(0).toISOString(),
    hostReady: false,
  });

  const handleHostReady = (event: Event) => {
    const detail = (event as CustomEvent<AvatarHostReadyPayload>).detail;
    if (detail?.hostId === state.runtimeHostId) {
      state.hostReady = true;
    }
  };

  window.addEventListener(CODE_AGENT_AVATAR_HOST_READY_EVENT, handleHostReady as EventListener);

  /**
   * 将当前会话状态同步到数字人运行时。
   */
  function sync(options: SyncBridgeOptions): void {
    const snapshot: AvatarRuntimeSnapshot = {
      source: "code-agent",
      version: 1,
      avatarMode: avatar.mode,
      provider: options.provider,
      status: options.status,
      expression: resolveExpression(options.status, options.isStreaming),
      activeFile: options.activeFile,
      latestAgentMessage: options.latestAgentMessage,
      latestUserMessage: options.latestUserMessage,
      isStreaming: options.isStreaming,
      runtimeHostId: state.runtimeHostId,
      emittedAt: new Date().toISOString(),
    };

    Object.assign(state, snapshot);
    window.dispatchEvent(
      new CustomEvent<AvatarRuntimeSnapshot>(CODE_AGENT_AVATAR_STATE_EVENT, {
        detail: snapshot,
      }),
    );
  }

  /**
   * 释放桥接层使用的事件监听。
   */
  function dispose(): void {
    window.removeEventListener(CODE_AGENT_AVATAR_HOST_READY_EVENT, handleHostReady as EventListener);
  }

  return {
    state,
    sync,
    dispose,
  };
}

/**
 * 根据插件状态推断数字人当前表达标签。
 */
function resolveExpression(status: string, isStreaming: boolean): AvatarExpression {
  if (isStreaming) {
    return "speaking";
  }

  if (status.includes("思考")) {
    return "thinking";
  }

  if (status.includes("应用") || status.includes("写回") || status.includes("执行")) {
    return "acting";
  }

  return "idle";
}
