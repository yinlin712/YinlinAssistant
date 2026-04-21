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
const railRef = ref<HTMLDivElement | null>(null);
const stickToBottom = ref(true);
const maxScroll = ref(0);
const sliderRatio = ref(1);
const sliderThumbHeight = ref(56);
const isSliderDragging = ref(false);

const normalizedMessages = computed(() => props.messages.map((message, index) => ({
  ...message,
  key: `${message.role}-${index}`,
  isContinuation: index > 0 && props.messages[index - 1].role === message.role,
})));

const streamingIsContinuation = computed(() => {
  const lastRole = props.messages[props.messages.length - 1]?.role;
  return lastRole === props.streamingMessage?.role;
});

const sliderThumbStyle = computed(() => {
  const railHeight = railRef.value?.clientHeight ?? 0;
  const travel = Math.max(railHeight - sliderThumbHeight.value, 0);
  return {
    height: `${sliderThumbHeight.value}px`,
    transform: `translateY(${travel * sliderRatio.value}px)`,
  };
});

watch(
  () => [props.messages, props.streamingMessage, props.showStatusBubble, props.statusText],
  async () => {
    await scrollToBottom();
    syncScrollMetrics();
  },
  { deep: true },
);

onMounted(async () => {
  await scrollToBottom(true);
  syncScrollMetrics();
  bindWheelListener();
  window.addEventListener("pointermove", handleWindowPointerMove);
  window.addEventListener("pointerup", stopSliderDrag);
  window.addEventListener("pointercancel", stopSliderDrag);
});

onBeforeUnmount(() => {
  unbindWheelListener();
  window.removeEventListener("pointermove", handleWindowPointerMove);
  window.removeEventListener("pointerup", stopSliderDrag);
  window.removeEventListener("pointercancel", stopSliderDrag);
});

/**
 * 根据滚动位置决定是否继续自动吸附到底部，并同步侧边滑块。
 */
function handleScroll(): void {
  const element = scrollRef.value;
  if (!element) {
    return;
  }

  const distanceFromBottom = element.scrollHeight - element.scrollTop - element.clientHeight;
  stickToBottom.value = distanceFromBottom < 48;
  syncScrollMetrics();
}

/**
 * 显式接手聊天区滚轮事件，避免外层舞台层抢占滚动。
 */
function handleWheel(event: WheelEvent): void {
  const element = scrollRef.value;
  if (!element || element.scrollHeight <= element.clientHeight) {
    return;
  }

  event.preventDefault();
  element.scrollTop = clampScrollTop(element.scrollTop + event.deltaY);
  handleScroll();
}

/**
 * 点击侧边滑轨时，直接将聊天历史滚动到对应位置。
 */
function handleRailPointerDown(event: PointerEvent): void {
  if (!railRef.value) {
    return;
  }

  event.preventDefault();
  syncScrollFromPointer(event.clientY);
}

/**
 * 按住滑块时进入拖动状态。
 */
function handleThumbPointerDown(event: PointerEvent): void {
  event.preventDefault();
  isSliderDragging.value = true;
  syncScrollFromPointer(event.clientY);
}

/**
 * 在窗口级别持续追踪滑块拖动。
 */
function handleWindowPointerMove(event: PointerEvent): void {
  if (!isSliderDragging.value) {
    return;
  }

  event.preventDefault();
  syncScrollFromPointer(event.clientY);
}

/**
 * 结束滑块拖动状态。
 */
function stopSliderDrag(): void {
  isSliderDragging.value = false;
}

/**
 * 按照指针在滑轨中的相对位置同步聊天容器滚动值。
 */
function syncScrollFromPointer(clientY: number): void {
  const element = scrollRef.value;
  const rail = railRef.value;
  if (!element || !rail) {
    return;
  }

  const rect = rail.getBoundingClientRect();
  const pointerY = clientY - rect.top - sliderThumbHeight.value / 2;
  const travel = Math.max(rect.height - sliderThumbHeight.value, 1);
  const ratio = clamp01(pointerY / travel);
  element.scrollTop = clampScrollTop(maxScroll.value * ratio);
  handleScroll();
}

/**
 * 在需要时将聊天视图自动滚动到底部。
 */
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

/**
 * 刷新聊天区的可滚动区间和侧边滑块位置。
 */
function syncScrollMetrics(): void {
  const element = scrollRef.value;
  const rail = railRef.value;
  if (!element) {
    maxScroll.value = 0;
    sliderRatio.value = 1;
    sliderThumbHeight.value = 56;
    return;
  }

  const nextMaxScroll = Math.max(0, element.scrollHeight - element.clientHeight);
  maxScroll.value = nextMaxScroll;
  sliderRatio.value = nextMaxScroll > 0 ? clamp01(element.scrollTop / nextMaxScroll) : 1;

  if (!rail) {
    return;
  }

  const visibleRatio = element.scrollHeight > 0
    ? clamp01(element.clientHeight / element.scrollHeight)
    : 1;
  sliderThumbHeight.value = Math.max(40, Math.round(rail.clientHeight * visibleRatio));
}

/**
 * 将滚动值限制在聊天容器允许的范围内。
 */
function clampScrollTop(value: number): number {
  return Math.max(0, Math.min(value, maxScroll.value));
}

/**
 * 绑定原生滚轮监听，确保在 Webview 中也能阻止默认滚动传播。
 */
function bindWheelListener(): void {
  scrollRef.value?.addEventListener("wheel", handleWheel, { passive: false });
}

/**
 * 解绑原生滚轮监听。
 */
function unbindWheelListener(): void {
  scrollRef.value?.removeEventListener("wheel", handleWheel);
}

function clamp01(value: number): number {
  return Math.max(0, Math.min(value, 1));
}
</script>

<template>
  <section class="chat-panel">
    <div ref="scrollRef" class="chat-scroll" @scroll="handleScroll">
      <div class="chat">
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

    <div ref="railRef" class="chat-scroll-rail" @pointerdown="handleRailPointerDown">
      <div
        class="chat-scroll-thumb"
        :class="{ 'is-disabled': maxScroll <= 0, 'is-dragging': isSliderDragging }"
        :style="sliderThumbStyle"
        @pointerdown.stop="handleThumbPointerDown"
      />
    </div>
  </section>
</template>
