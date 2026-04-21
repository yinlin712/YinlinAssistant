<script setup lang="ts">
import { computed, ref, watch } from "vue";
import type { AvatarBridgeState } from "../../virtual/bridge";
import type { AvatarConfig, AvatarPresetConfig, VisualPreferences } from "../types";
import VirtualAvatarStage from "./avatar/VirtualAvatarStage.vue";

const props = defineProps<{
  avatar: AvatarConfig;
  status: string;
  latestAgentMessage: string;
  isStreaming: boolean;
  avatarState: AvatarBridgeState;
  visualPreferences: VisualPreferences;
  interactionMode: boolean;
}>();

const emit = defineEmits<{
  (event: "update-visual-preferences", value: Partial<VisualPreferences>): void;
  (event: "toggle-interaction-mode"): void;
}>();

const stageRef = ref<InstanceType<typeof VirtualAvatarStage> | null>(null);
const toolbarExpanded = ref(false);
const selectedPresetId = ref(props.avatar.defaultPresetId || props.avatar.presets[0]?.id || "");

const visiblePresets = computed<AvatarPresetConfig[]>(() => props.avatar.presets);

const resolvedAvatar = computed<AvatarConfig>(() => {
  const selectedPreset = props.avatar.presets.find((preset) => preset.id === selectedPresetId.value);

  return {
    ...props.avatar,
    avatarUri: selectedPreset?.avatarUri || props.avatar.avatarUri,
    vrmUri: selectedPreset?.vrmUri || props.avatar.vrmUri,
  };
});

watch(
  () => [props.avatar.defaultPresetId, props.avatar.presets],
  () => {
    const fallbackPresetId = props.avatar.defaultPresetId || props.avatar.presets[0]?.id || "";
    const stillExists = props.avatar.presets.some((preset) => preset.id === selectedPresetId.value);
    if (!stillExists) {
      selectedPresetId.value = fallbackPresetId;
    }
  },
  { deep: true, immediate: true },
);

/**
 * 切换当前数字人预设。
 */
function selectPreset(presetId: string): void {
  selectedPresetId.value = presetId;
}

/**
 * 重置数字人的旋转、抬升和拖拽状态。
 */
function resetAvatarState(): void {
  stageRef.value?.resetInteraction();
}

/**
 * 重新播放欢迎语。
 */
function replayGreeting(): void {
  stageRef.value?.replayGreeting();
}

/**
 * 更新背景透明度。
 */
function handleBackgroundOpacityInput(event: Event): void {
  emit("update-visual-preferences", {
    backgroundOpacity: (event.target as HTMLInputElement).valueAsNumber,
  });
}

/**
 * 更新聊天层透明度。
 */
function handleChatOpacityInput(event: Event): void {
  emit("update-visual-preferences", {
    chatOpacity: (event.target as HTMLInputElement).valueAsNumber,
  });
}
</script>

<template>
  <section class="avatar-backdrop">
    <VirtualAvatarStage
      ref="stageRef"
      :avatar="resolvedAvatar"
      :status="props.status"
      :latest-agent-message="props.latestAgentMessage"
      :is-streaming="props.isStreaming"
      :avatar-state="props.avatarState"
      :interaction-mode="props.interactionMode"
    />

    <div class="avatar-toolbar">
      <button
        type="button"
        class="avatar-toolbar-toggle"
        :aria-expanded="toolbarExpanded"
        aria-label="展开数字人工具栏"
        @click="toolbarExpanded = !toolbarExpanded"
      >
        ⌘
      </button>

      <div v-if="toolbarExpanded" class="avatar-toolbar-panel">
        <div class="avatar-toolbar-section">
          <span class="avatar-toolbar-title">切换数字人</span>
          <div class="avatar-toolbar-presets">
            <button
              v-for="preset in visiblePresets"
              :key="preset.id"
              type="button"
              class="avatar-toolbar-chip"
              :class="{ 'is-active': preset.id === selectedPresetId }"
              @click="selectPreset(preset.id)"
            >
              {{ preset.label }}
            </button>
          </div>
        </div>

        <div class="avatar-toolbar-section avatar-toolbar-sliders">
          <label class="avatar-toolbar-slider">
            <span>背景透明度 {{ props.visualPreferences.backgroundOpacity }}%</span>
            <input
              type="range"
              min="0"
              max="100"
              :value="props.visualPreferences.backgroundOpacity"
              @input="handleBackgroundOpacityInput"
            >
          </label>

          <label class="avatar-toolbar-slider">
            <span>聊天透明度 {{ props.visualPreferences.chatOpacity }}%</span>
            <input
              type="range"
              min="0"
              max="100"
              :value="props.visualPreferences.chatOpacity"
              @input="handleChatOpacityInput"
            >
          </label>
        </div>

        <div class="avatar-toolbar-section avatar-toolbar-actions">
          <button type="button" class="avatar-toolbar-action" @click="emit('toggle-interaction-mode')">
            {{ props.interactionMode ? "返回对话" : "数字人拖拽" }}
          </button>
          <button type="button" class="avatar-toolbar-action" @click="resetAvatarState">
            重置状态
          </button>
          <button type="button" class="avatar-toolbar-action" @click="replayGreeting">
            打招呼
          </button>
        </div>
      </div>
    </div>
  </section>
</template>
