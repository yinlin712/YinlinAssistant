<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import type { ChatMessage } from "../types";
import MarkdownContent from "./MarkdownContent.vue";

const props = withDefaults(
  defineProps<{
    messages: ChatMessage[];
    streamingMessage?: ChatMessage | null;
    statusText?: string;
    showStatusBubble?: boolean;
  }>(),
  {
    streamingMessage: null,
    statusText: "",
    showStatusBubble: false,
  },
);

const scrollRef = ref<HTMLDivElement | null>(null);
const stickToBottom = ref(true);
let resizeObserver: ResizeObserver | undefined;

const normalizedMessages = computed(() => props.messages.map((message, index) => ({
  ...message,
  key: `${message.role}-${index}`,
  isContinuation: index > 0 && props.messages[index - 1].role === message.role,
})));

const streamingIsContinuation = computed(() => {
  const lastRole = props.messages[props.messages.length - 1]?.role;
  return lastRole === props.streamingMessage?.role;
});

watch(
  () => [props.messages, props.streamingMessage, props.showStatusBubble, props.statusText],
  async () => {
    await scrollToBottom();
  },
  { deep: true },
);

onMounted(async () => {
  await scrollToBottom(true);
  bindResizeObserver();
  bindWheelListener();
});

onBeforeUnmount(() => {
  resizeObserver?.disconnect();
  unbindWheelListener();
});

function bindResizeObserver(): void {
  if (typeof ResizeObserver === "undefined" || !scrollRef.value) {
    return;
  }

  resizeObserver = new ResizeObserver(() => {
    if (stickToBottom.value) {
      void scrollToBottom(true);
    }
  });
  resizeObserver.observe(scrollRef.value);
}

function handleScroll(): void {
  const element = scrollRef.value;
  if (!element) {
    return;
  }

  const distanceFromBottom = element.scrollHeight - element.scrollTop - element.clientHeight;
  stickToBottom.value = distanceFromBottom < 48;
}

async function scrollToBottom(force: boolean = false): Promise<void> {
  await nextTick();

  const element = scrollRef.value;
  if (!element) {
    return;
  }

  if (!force && !stickToBottom.value) {
    return;
  }

  element.scrollTop = element.scrollHeight;
}

function handleScrollKeydown(event: KeyboardEvent): void {
  const element = scrollRef.value;
  if (!element || element.scrollHeight <= element.clientHeight) {
    return;
  }

  const pageStep = Math.max(element.clientHeight * 0.82, 120);
  const lineStep = 72;
  const keyActions: Record<string, number | "top" | "bottom"> = {
    ArrowUp: -lineStep,
    ArrowDown: lineStep,
    PageUp: -pageStep,
    PageDown: pageStep,
    Home: "top",
    End: "bottom",
  };

  const action = keyActions[event.key];
  if (action === undefined) {
    return;
  }

  event.preventDefault();
  event.stopPropagation();

  if (action === "top") {
    element.scrollTop = 0;
  } else if (action === "bottom") {
    element.scrollTop = element.scrollHeight;
  } else {
    element.scrollTop = clampScrollTop(element.scrollTop + action);
  }

  handleScroll();
}

function bindWheelListener(): void {
  scrollRef.value?.addEventListener("wheel", stopWheelPropagation, { passive: false });
}

function unbindWheelListener(): void {
  scrollRef.value?.removeEventListener("wheel", stopWheelPropagation);
}

function stopWheelPropagation(event: WheelEvent): void {
  event.stopPropagation();
}

function clampScrollTop(value: number): number {
  const element = scrollRef.value;
  const maxScroll = element ? Math.max(0, element.scrollHeight - element.clientHeight) : 0;
  return Math.max(0, Math.min(value, maxScroll));
}
</script>

<template>
  <section class="chat-panel">
    <div
      ref="scrollRef"
      class="chat-scroll"
      tabindex="0"
      @scroll="handleScroll"
      @wheel.capture="stopWheelPropagation"
      @keydown="handleScrollKeydown"
    >
      <div class="chat">
        <div class="chat-spacer" aria-hidden="true" />

        <div
          v-for="message in normalizedMessages"
          :key="message.key"
          :class="['message', message.role, { 'is-continuation': message.isContinuation }]"
        >
          <MarkdownContent :content="message.content" />
        </div>

        <div
          v-if="props.streamingMessage"
          :class="[
            'message',
            props.streamingMessage.role,
            'streaming',
            { 'is-continuation': streamingIsContinuation },
          ]"
        >
          <MarkdownContent :content="props.streamingMessage.content" />
        </div>

        <div v-else-if="props.showStatusBubble" class="message agent message-status">
          <div class="message-status-line">
            <span class="message-status-dot" />
            <span>{{ props.statusText }}</span>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>
