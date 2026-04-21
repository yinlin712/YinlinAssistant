<script setup lang="ts">
import { computed, ref } from "vue";
import type { PendingProposalPayload } from "../types";

const props = defineProps<{
  proposal?: PendingProposalPayload | null;
  statusText?: string;
  isBusy?: boolean;
}>();

const emit = defineEmits<{
  (event: "submitPrompt", prompt: string): void;
  (event: "applyPendingActions"): void;
  (event: "discardPendingActions"): void;
}>();

const value = ref("");

const proposalSummary = computed(() => {
  if (!props.proposal) {
    return "";
  }

  if (props.proposal.isStreaming) {
    return "正在生成修改方案...";
  }

  return props.proposal.summary;
});

const normalizedStatusText = computed(() => {
  return props.statusText || "待命";
});

/**
 * 提交当前输入框中的请求。
 */
function submitCurrentValue() {
  const nextValue = value.value.trim();
  if (!nextValue) {
    return;
  }

  emit("submitPrompt", nextValue);
  value.value = "";
}

/**
 * 支持 Enter 直接发送，Shift + Enter 换行。
 */
function handleKeyDown(event: KeyboardEvent) {
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
      <textarea
        v-model="value"
        class="composer-textarea"
        placeholder="输入需求，例如：解释这个函数；帮我继续封装这个函数；请检索整个项目并规划一组多文件修改。"
        @keydown="handleKeyDown"
      />
      <button type="submit" class="composer-submit" aria-label="发送">
        发送
      </button>
    </div>
  </form>
</template>
