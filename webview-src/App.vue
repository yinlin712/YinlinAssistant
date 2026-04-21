<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { createAvatarBridge } from "../virtual/bridge";
import { readAvatarConfig } from "../virtual/client-config";
import ChatList from "./components/ChatList.vue";
import Composer from "./components/Composer.vue";
import AvatarPanel from "./components/AvatarPanel.vue";
import type {
  ChatMessage,
  HydratePayload,
  MessageChunkPayload,
  PendingProposalPayload,
  PersistedWebviewState,
  ProposalActionPreview,
  StatusPayload,
  VisualPreferences,
  WebviewIncomingMessage,
} from "./types";
import { getVsCodeApi } from "./vscode";

const CURRENT_SESSION_ID = document.body.dataset.sessionId ?? "";
const avatar = readAvatarConfig();
const avatarBridge = createAvatarBridge(avatar);
const vscode = getVsCodeApi();

const defaultState = createDefaultState(CURRENT_SESSION_ID);
const initialState = readPersistedState(CURRENT_SESSION_ID, defaultState);

const messages = ref<ChatMessage[]>(initialState.messages);
const status = ref(initialState.status);
const provider = ref(initialState.provider);
const activeFile = ref(initialState.activeFile);
const emptyProposalText = ref(initialState.emptyProposalText);
const proposal = ref<PendingProposalPayload | null>(initialState.proposal);
const streamingAgentContent = ref(initialState.streamingAgentContent);
const localStatus = ref("");
const visualPreferences = ref<VisualPreferences>(initialState.visualPreferences);
const avatarInteractionMode = ref(false);

const streamingMessage = computed<ChatMessage | null>(() => {
  if (!streamingAgentContent.value) {
    return null;
  }

  return {
    role: "agent",
    content: streamingAgentContent.value,
  };
});

const latestAgentMessage = computed(() => {
  if (streamingAgentContent.value) {
    return streamingAgentContent.value;
  }

  const latest = [...messages.value].reverse().find((message) => message.role === "agent");
  return latest?.content ?? "";
});

const latestUserMessage = computed(() => {
  const latest = [...messages.value].reverse().find((message) => message.role === "user");
  return latest?.content ?? "";
});

const displayStatus = computed(() => {
  if (proposal.value?.isStreaming) {
    return "正在生成修改方案...";
  }

  if (localStatus.value) {
    return localStatus.value;
  }

  return status.value;
});

const isBusy = computed(() => {
  return Boolean(streamingAgentContent.value)
    || Boolean(proposal.value?.isStreaming)
    || Boolean(localStatus.value)
    || isBusyStatus(status.value);
});

const showStatusBubble = computed(() => {
  return isBusy.value && !streamingAgentContent.value;
});

const shellStyle = computed<Record<string, string>>(() => ({
  "--code-agent-background-opacity": String(visualPreferences.value.backgroundOpacity / 100),
  "--code-agent-chat-opacity": String(visualPreferences.value.chatOpacity / 100),
}));

/**
 * 在 Webview 状态变化时持久化到 VS Code 内部缓存。
 */
watch(
  [messages, status, provider, activeFile, emptyProposalText, proposal, streamingAgentContent, visualPreferences],
  () => {
    const nextState: PersistedWebviewState = {
      sessionId: CURRENT_SESSION_ID,
      messages: cloneMessages(messages.value),
      status: status.value,
      provider: provider.value,
      activeFile: activeFile.value,
      emptyProposalText: emptyProposalText.value,
      proposal: cloneProposal(proposal.value),
      streamingAgentContent: streamingAgentContent.value,
      visualPreferences: {
        backgroundOpacity: visualPreferences.value.backgroundOpacity,
        chatOpacity: visualPreferences.value.chatOpacity,
      },
    };

    vscode.setState(nextState);
  },
  { deep: true, immediate: true },
);

/**
 * 将当前会话状态同步到 AIRI 兼容桥接层。
 */
watch(
  [messages, status, provider, activeFile, streamingAgentContent],
  () => {
    avatarBridge.sync({
      status: status.value,
      provider: provider.value,
      activeFile: activeFile.value,
      latestAgentMessage: latestAgentMessage.value,
      latestUserMessage: latestUserMessage.value,
      isStreaming: Boolean(streamingAgentContent.value),
    });
  },
  { deep: true, immediate: true },
);

/**
 * 监听插件端推送的消息，并同步前端显示状态。
 */
function handleMessage(event: MessageEvent<WebviewIncomingMessage>) {
  const message = event.data;

  if (message.type === "hydrate") {
    const payload = message.payload as HydratePayload;
    messages.value = payload.messages;
    status.value = payload.status;
    localStatus.value = "";
    provider.value = payload.provider;
    activeFile.value = payload.activeFile || payload.noActiveFile;
    emptyProposalText.value = payload.proposalEmpty;
    proposal.value = payload.pendingProposal;
    streamingAgentContent.value = "";
    return;
  }

  if (message.type === "message") {
    const payload = message.payload as ChatMessage;
    if (payload.role === "agent") {
      streamingAgentContent.value = "";
      localStatus.value = "";
    }

    messages.value = [...messages.value, payload];
    return;
  }

  if (message.type === "messageChunk") {
    const payload = message.payload as MessageChunkPayload;
    if (payload.role === "agent") {
      localStatus.value = "";
      streamingAgentContent.value += payload.chunk;
    }
    return;
  }

  if (message.type === "status") {
    const payload = message.payload as StatusPayload;
    status.value = payload.status;
    localStatus.value = "";
    provider.value = payload.provider;
    activeFile.value = payload.activeFile || payload.noActiveFile;
    return;
  }

  if (message.type === "proposal") {
    localStatus.value = "";
    proposal.value = message.payload as PendingProposalPayload;
    return;
  }

  if (message.type === "clearProposal") {
    const payload = message.payload as { emptyText: string };
    localStatus.value = "";
    proposal.value = null;
    emptyProposalText.value = payload.emptyText;
  }
}

onMounted(() => {
  window.addEventListener("message", handleMessage);
});

onUnmounted(() => {
  window.removeEventListener("message", handleMessage);
  avatarBridge.dispose();
});

/**
 * 将用户输入统一封装为 Webview 消息并发送给插件端。
 */
function submitPrompt(prompt: string) {
  localStatus.value = "正在发送请求...";
  vscode.postMessage({
    type: "submitPrompt",
    payload: { prompt },
  });
}

function applyPendingActions() {
  vscode.postMessage({ type: "applyPendingActions" });
}

function discardPendingActions() {
  vscode.postMessage({ type: "discardPendingActions" });
}

/**
 * 读取 VS Code 为当前 Webview 缓存的状态。
 */
function readPersistedState(
  sessionId: string,
  fallbackState: PersistedWebviewState,
): PersistedWebviewState {
  const rawState = vscode.getState() as Partial<PersistedWebviewState> | undefined;
  if (!rawState || rawState.sessionId !== sessionId) {
    return fallbackState;
  }

  return {
    sessionId: rawState.sessionId ?? fallbackState.sessionId,
    messages: rawState.messages ?? fallbackState.messages,
    status: rawState.status ?? fallbackState.status,
    provider: rawState.provider ?? fallbackState.provider,
    activeFile: rawState.activeFile ?? fallbackState.activeFile,
    emptyProposalText: rawState.emptyProposalText ?? fallbackState.emptyProposalText,
    proposal: rawState.proposal ?? fallbackState.proposal,
    streamingAgentContent: rawState.streamingAgentContent ?? fallbackState.streamingAgentContent,
    visualPreferences: rawState.visualPreferences ?? fallbackState.visualPreferences,
  };
}

/**
 * 构造 Webview 初始状态。
 */
function createDefaultState(sessionId: string): PersistedWebviewState {
  return {
    sessionId,
    messages: [],
    status: "待命",
    provider: "local",
    activeFile: "无活动文件",
    emptyProposalText: "当前还没有待确认的变更方案。",
    proposal: null,
    streamingAgentContent: "",
    visualPreferences: {
      backgroundOpacity: 24,
      chatOpacity: 34,
    },
  };
}

/**
 * 将消息数组复制为可安全持久化的普通对象。
 */
function cloneMessages(source: ChatMessage[]): ChatMessage[] {
  return source.map((message) => ({
    role: message.role,
    content: message.content,
  }));
}

/**
 * 将待确认方案复制为可安全持久化的普通对象。
 */
function cloneProposal(source: PendingProposalPayload | null): PendingProposalPayload | null {
  if (!source) {
    return null;
  }

  return {
    title: source.title,
    summary: source.summary,
    isStreaming: source.isStreaming,
    actions: source.actions.map(cloneProposalAction),
  };
}

/**
 * 复制单个方案动作，避免将响应式代理直接写入 VS Code 状态缓存。
 */
function cloneProposalAction(source: ProposalActionPreview): ProposalActionPreview {
  return {
    kind: source.kind,
    targetFile: source.targetFile,
    summary: source.summary,
    diffText: source.diffText,
  };
}

/**
 * 更新界面透明度偏好。
 */
function updateVisualPreferences(nextValue: Partial<VisualPreferences>): void {
  visualPreferences.value = {
    backgroundOpacity: nextValue.backgroundOpacity ?? visualPreferences.value.backgroundOpacity,
    chatOpacity: nextValue.chatOpacity ?? visualPreferences.value.chatOpacity,
  };
}

/**
 * 切换数字人专注拖拽模式。
 */
function toggleAvatarInteractionMode(): void {
  avatarInteractionMode.value = !avatarInteractionMode.value;
}

/**
 * 判断当前状态是否属于需要持续反馈的处理中阶段。
 */
function isBusyStatus(value: string): boolean {
  if (!value) {
    return false;
  }

  if (value.includes("待命") || value.includes("已响应")) {
    return false;
  }

  return /发送|思考|检索|生成|规划|分析|应用|写回|执行|流式|patch|处理中/i.test(value);
}
</script>

<template>
  <main class="agent-shell" :style="shellStyle">
    <AvatarPanel
      v-if="avatar.enabled"
      :avatar="avatar"
      :status="status"
      :latest-agent-message="latestAgentMessage"
      :is-streaming="Boolean(streamingAgentContent)"
      :avatar-state="avatarBridge.state"
      :visual-preferences="visualPreferences"
      :interaction-mode="avatarInteractionMode"
      @update-visual-preferences="updateVisualPreferences"
      @toggle-interaction-mode="toggleAvatarInteractionMode"
    />
    <div class="agent-overlay" :class="{ 'is-avatar-focus': avatarInteractionMode }">
      <section class="agent-chat-band">
        <ChatList
          :messages="messages"
          :streaming-message="streamingMessage"
          :status-text="displayStatus"
          :show-status-bubble="showStatusBubble"
        />
      </section>

      <footer class="agent-composer-layer">
        <Composer
          :proposal="proposal"
          :status-text="displayStatus"
          :is-busy="isBusy"
          @submit-prompt="submitPrompt"
          @apply-pending-actions="applyPendingActions"
          @discard-pending-actions="discardPendingActions"
        />
      </footer>
    </div>
  </main>
</template>
