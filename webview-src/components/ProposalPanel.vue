<script setup lang="ts">
import type { PendingProposalPayload } from "../types";

const props = defineProps<{
  proposal: PendingProposalPayload | null;
  emptyText: string;
}>();

const emit = defineEmits<{
  (event: "apply"): void;
  (event: "discard"): void;
}>();

/**
 * 根据 diff 行前缀返回用于着色的样式类名。
 */
function buildDiffLineClassName(line: string): string {
  if (line.startsWith("+ ")) {
    return "diff-line diff-added";
  }

  if (line.startsWith("- ")) {
    return "diff-line diff-removed";
  }

  if (line.startsWith("@@")) {
    return "diff-line diff-hunk";
  }

  if (line.startsWith("+++") || line.startsWith("---")) {
    return "diff-line diff-header";
  }

  return "diff-line";
}
</script>

<template>
  <section :class="['proposal-panel', { 'is-empty': !props.proposal }]">
    <div class="proposal-summary">
      <div class="proposal-summary-top">
        <strong>{{ props.proposal?.title ?? "待确认变更" }}</strong>
        <span v-if="props.proposal?.isStreaming" class="proposal-badge">生成中</span>
      </div>
      <span>{{ props.proposal?.summary ?? props.emptyText }}</span>
    </div>

    <template v-if="props.proposal">
      <div v-if="props.proposal.isStreaming" class="proposal-streaming-hint">
        正在根据模型输出持续刷新 patch，待生成完成后才能应用。
      </div>
      <div v-else class="proposal-controls">
        <button class="proposal-button" type="button" @click="emit('apply')">
          应用修改
        </button>
        <button class="proposal-button secondary" type="button" @click="emit('discard')">
          清空预览
        </button>
      </div>

      <div class="proposal-list">
        <article
          v-for="action in props.proposal.actions"
          :key="`${action.kind}-${action.targetFile}`"
          class="proposal-card"
        >
          <div class="proposal-card-top">
            <h3>{{ action.targetFile }}</h3>
            <span class="proposal-kind">{{ action.kind }}</span>
          </div>
          <pre class="proposal-diff"><span
            v-for="(line, index) in action.diffText.split('\n')"
            :key="`${action.targetFile}-${index}`"
            :class="buildDiffLineClassName(line)"
          >{{ line }}</span></pre>
        </article>
      </div>
    </template>

    <div v-else class="proposal-empty">
      <span class="proposal-empty-line" />
      <span class="proposal-empty-line short" />
      <span class="proposal-empty-line" />
    </div>
  </section>
</template>
