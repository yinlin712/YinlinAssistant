<script setup lang="ts">
import { computed } from "vue";
import type { PendingProposalPayload } from "../types";

const props = defineProps<{
  modelValue: string;
  proposal?: PendingProposalPayload | null;
  statusText?: string;
  isBusy?: boolean;
  voiceEnabled?: boolean;
  isVoiceRecording?: boolean;
  isVoiceTranscribing?: boolean;
}>();

const emit = defineEmits<{
  (event: "update:modelValue", value: string): void;
  (event: "submitPrompt", prompt: string): void;
  (event: "applyPendingActions"): void;
  (event: "discardPendingActions"): void;
  (event: "toggleVoiceInput"): void;
}>();

const proposalSummary = computed(() => {
  if (!props.proposal) {
    return "";
  }

  if (props.proposal.isStreaming) {
    return "正在生成修改方案...";
  }

  return props.proposal.summary;
});

const normalizedStatusText = computed(() => props.statusText || "待命");

const microphoneButtonLabel = computed(() => {
  if (props.isVoiceTranscribing) {
    return "识别中";
  }

  if (props.isVoiceRecording) {
    return "结束";
  }

  return "麦克风";
});

function submitCurrentValue(): void {
  const nextValue = props.modelValue.trim();
  if (!nextValue) {
    return;
  }

  emit("submitPrompt", nextValue);
  emit("update:modelValue", "");
}

function handleInput(event: Event): void {
  emit("update:modelValue", (event.target as HTMLTextAreaElement).value);
}

function handleKeyDown(event: KeyboardEvent): void {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    submitCurrentValue();
  }
}
</script>

<template>
  <form class="composer" @submit.prevent="submitCurrentValue">
    <div class="composer-status" :class="{ 'is-busy': props.isBusy }">
      <span class="composer-status-dot" />
      <span class="composer-status-text">{{ normalizedStatusText }}</span>
    </div>

    <div v-if="props.proposal" class="composer-proposal">
      <span class="composer-proposal-text">{{ proposalSummary }}</span>
      <div class="composer-proposal-actions">
        <button
          type="button"
          class="composer-proposal-button composer-proposal-button--ghost"
          @click="emit('discardPendingActions')"
        >
          取消
        </button>
        <button
          type="button"
          class="composer-proposal-button"
          :disabled="props.proposal.isStreaming"
          @click="emit('applyPendingActions')"
        >
          应用
        </button>
      </div>
    </div>

    <div class="composer-body">
      <div class="composer-input-shell">
        <textarea
          :value="props.modelValue"
          class="composer-textarea"
          placeholder="输入需求，例如：解释这个函数；帮我继续封装这个函数；请检索整个项目并规划一组多文件修改。"
          @input="handleInput"
          @keydown="handleKeyDown"
        />
        <button
          v-if="props.voiceEnabled"
          type="button"
          class="composer-microphone"
          :class="{ 'is-recording': props.isVoiceRecording, 'is-transcribing': props.isVoiceTranscribing }"
          :disabled="props.isVoiceTranscribing"
          @click="emit('toggleVoiceInput')"
        >
          {{ microphoneButtonLabel }}
        </button>
      </div>

      <button type="submit" class="composer-submit" aria-label="发送">
        发送
      </button>
    </div>
  </form>
</template>
