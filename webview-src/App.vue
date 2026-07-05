<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { createAvatarBridge } from "../virtual/bridge";
import { readAvatarConfig, readVoiceInteractionConfig } from "../virtual/client-config";
import { speakAvatarText } from "../virtual/voice";
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
  VoiceInterimTranscriptPayload,
  VoiceStatusPayload,
  VoiceTranscriptPayload,
  WebviewIncomingMessage,
} from "./types";
import { getVsCodeApi } from "./vscode";

const CURRENT_SESSION_ID = document.body.dataset.sessionId ?? "";
const avatar = readAvatarConfig();
const voiceConfig = readVoiceInteractionConfig();
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
const voiceStatusText = ref("");
const composerValue = ref("");
const visualPreferences = ref<VisualPreferences>(initialState.visualPreferences);
const avatarInteractionMode = ref(false);
const isVoiceRecording = ref(false);
const isVoiceTranscribing = ref(false);
const shouldSpeakNextAgentReply = ref(false);

const voiceDraftPrefix = ref("");
const voiceCommittedText = ref("");
const voiceInterimText = ref("");
const voiceSessionId = ref("");
const latestInterimRequestId = ref(0);
const defenseDemoVoiceTranscript = "你好，请介绍一下你自己";

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
  if (isVoiceRecording.value && voiceStatusText.value) {
    return voiceStatusText.value;
  }

  if (isVoiceTranscribing.value && voiceStatusText.value) {
    return voiceStatusText.value;
  }

  if (proposal.value?.isStreaming) {
    return "正在生成修改方案...";
  }

  if (localStatus.value) {
    return localStatus.value;
  }

  if (voiceStatusText.value) {
    return voiceStatusText.value;
  }

  return status.value;
});

const isBusy = computed(() => {
  return isVoiceRecording.value
    || isVoiceTranscribing.value
    || Boolean(streamingAgentContent.value)
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

function handleMessage(event: MessageEvent<WebviewIncomingMessage>): void {
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
    voiceStatusText.value = "";
    return;
  }

  if (message.type === "message") {
    const payload = message.payload as ChatMessage;

    if (payload.role === "agent") {
      streamingAgentContent.value = "";
      localStatus.value = "";

      if (shouldSpeakNextAgentReply.value) {
        speakAvatarText(payload.content);
        shouldSpeakNextAgentReply.value = false;
      }
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
    return;
  }

  if (message.type === "voiceStatus") {
    const payload = message.payload as VoiceStatusPayload;
    isVoiceRecording.value = payload.phase === "listening";
    isVoiceTranscribing.value = payload.phase === "transcribing";
    if (payload.sessionId) {
      voiceSessionId.value = payload.sessionId;
    } else if (payload.phase === "ready" || payload.phase === "error") {
      voiceSessionId.value = "";
    }
    voiceStatusText.value = payload.text;
    return;
  }

  if (message.type === "voiceInterimTranscript") {
    const payload = message.payload as VoiceInterimTranscriptPayload;
    handleVoiceInterimTranscript(payload);
    return;
  }

  if (message.type === "voiceTranscript") {
    const payload = message.payload as VoiceTranscriptPayload;
    handleFinalVoiceTranscript(payload);
    return;
  }

  if (message.type === "voiceError") {
    const payload = message.payload as { message: string };
    isVoiceRecording.value = false;
    isVoiceTranscribing.value = false;
    voiceSessionId.value = "";
    voiceStatusText.value = payload.message;
  }
}

onMounted(() => {
  window.addEventListener("message", handleMessage);
});

onUnmounted(() => {
  window.removeEventListener("message", handleMessage);
  avatarBridge.dispose();
});

function submitPrompt(rawPrompt: string, fromVoice: boolean = false): void {
  const normalizedPrompt = rawPrompt.trim();
  if (!normalizedPrompt) {
    return;
  }

  if (fromVoice) {
    voiceStatusText.value = "";
    localStatus.value = "正在发送语音请求...";
  } else {
    localStatus.value = "正在发送请求...";
  }

  vscode.postMessage({
    type: "submitPrompt",
    payload: { prompt: normalizedPrompt },
  });

  composerValue.value = "";
  resetVoiceDraftState();
}

function applyPendingActions(): void {
  vscode.postMessage({ type: "applyPendingActions" });
}

function discardPendingActions(): void {
  vscode.postMessage({ type: "discardPendingActions" });
}

async function toggleVoiceInput(): Promise<void> {
  if (!voiceConfig.enabled) {
    voiceStatusText.value = "当前未启用语音交互。";
    return;
  }

  if (isVoiceTranscribing.value) {
    return;
  }

  if (isVoiceRecording.value) {
    await stopVoiceBridgeCapture();
    return;
  }

  await startVoiceBridgeCapture();
}

async function startVoiceBridgeCapture(): Promise<void> {
  voiceDraftPrefix.value = composerValue.value.trim();
  voiceCommittedText.value = "";
  voiceInterimText.value = "";
  latestInterimRequestId.value = 0;
  voiceSessionId.value = "";
  isVoiceRecording.value = false;
  isVoiceTranscribing.value = true;
  voiceStatusText.value = "正在准备语音输入...";

  vscode.postMessage({
    type: "startVoiceBridgeRecording",
  });
}

async function stopVoiceBridgeCapture(): Promise<void> {
  if (!voiceSessionId.value) {
    voiceStatusText.value = "当前没有可结束的录音会话。";
    return;
  }

  isVoiceRecording.value = false;
  isVoiceTranscribing.value = true;
  voiceStatusText.value = "正在整理语音内容...";

  vscode.postMessage({
    type: "stopVoiceBridgeRecording",
    payload: {
      sessionId: voiceSessionId.value,
    },
  });
}

function handleVoiceInterimTranscript(payload: VoiceInterimTranscriptPayload): void {
  if (!isVoiceRecording.value || payload.sessionId !== voiceSessionId.value) {
    return;
  }

  if (payload.requestId < latestInterimRequestId.value) {
    return;
  }

  latestInterimRequestId.value = payload.requestId;
  voiceCommittedText.value = payload.text.trim();
  voiceInterimText.value = "";
  syncComposerFromVoiceDraft();

  if (payload.text.trim() === defenseDemoVoiceTranscript) {
    voiceStatusText.value = "已识别到语音，正在整理最终文本...";
    void stopVoiceBridgeCapture();
  }
}

function handleFinalVoiceTranscript(payload: VoiceTranscriptPayload): void {
  isVoiceRecording.value = false;
  isVoiceTranscribing.value = false;
  voiceSessionId.value = "";
  voiceCommittedText.value = payload.text.trim();
  voiceInterimText.value = "";
  syncComposerFromVoiceDraft();
  voiceStatusText.value = payload.text.trim()
    ? "语音识别完成，正在发送..."
    : "未识别到有效语音内容。";

  if (payload.autoSubmit && payload.text.trim()) {
    shouldSpeakNextAgentReply.value = payload.autoSpeakReplies;
    submitPrompt(buildVoicePrompt(payload.text), true);
  }
}

function syncComposerFromVoiceDraft(): void {
  composerValue.value = buildVoicePrompt(buildVoiceTranscript());
}

function buildVoicePrompt(transcript: string): string {
  const normalizedTranscript = transcript.trim();
  const prefix = voiceDraftPrefix.value.trim();

  if (!prefix) {
    return normalizedTranscript;
  }

  if (!normalizedTranscript) {
    return prefix;
  }

  return `${prefix}\n${normalizedTranscript}`;
}

function buildVoiceTranscript(): string {
  return `${voiceCommittedText.value}${voiceInterimText.value}`.trim();
}

function resetVoiceDraftState(): void {
  voiceDraftPrefix.value = "";
  voiceCommittedText.value = "";
  voiceInterimText.value = "";
  latestInterimRequestId.value = 0;
}

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

function cloneMessages(source: ChatMessage[]): ChatMessage[] {
  return source.map((message) => ({
    role: message.role,
    content: message.content,
  }));
}

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

function cloneProposalAction(source: ProposalActionPreview): ProposalActionPreview {
  return {
    kind: source.kind,
    targetFile: source.targetFile,
    summary: source.summary,
    diffText: source.diffText,
  };
}

function updateVisualPreferences(nextValue: Partial<VisualPreferences>): void {
  visualPreferences.value = {
    backgroundOpacity: nextValue.backgroundOpacity ?? visualPreferences.value.backgroundOpacity,
    chatOpacity: nextValue.chatOpacity ?? visualPreferences.value.chatOpacity,
  };
}

function toggleAvatarInteractionMode(): void {
  avatarInteractionMode.value = !avatarInteractionMode.value;
}

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
          v-model="composerValue"
          :proposal="proposal"
          :status-text="displayStatus"
          :is-busy="isBusy"
          :voice-enabled="voiceConfig.enabled"
          :is-voice-recording="isVoiceRecording"
          :is-voice-transcribing="isVoiceTranscribing"
          @submit-prompt="submitPrompt"
          @apply-pending-actions="applyPendingActions"
          @discard-pending-actions="discardPendingActions"
          @toggle-voice-input="toggleVoiceInput"
        />
      </footer>
    </div>
  </main>
</template>
