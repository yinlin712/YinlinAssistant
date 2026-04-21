<script setup lang="ts">
const props = defineProps<{
  status: string;
  provider: string;
  activeFile: string;
}>();

/**
 * 将长路径压缩为更适合侧边栏展示的形式。
 */
function formatActiveFile(activeFile: string): string {
  const normalized = activeFile.replace(/\\/g, "/");
  const segments = normalized.split("/").filter(Boolean);
  if (segments.length <= 2) {
    return activeFile;
  }

  return `${segments[segments.length - 2]}/${segments[segments.length - 1]}`;
}
</script>

<template>
  <section class="status-bar">
    <div class="status-main">
      <span class="status-dot" aria-hidden="true" />
      <span class="status-label">{{ props.status }}</span>
    </div>
    <span class="status-provider">{{ props.provider }}</span>
    <span class="status-file" :title="props.activeFile">
      {{ formatActiveFile(props.activeFile) }}
    </span>
  </section>
</template>
