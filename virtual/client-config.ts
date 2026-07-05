import type {
  AvatarConfig,
  AvatarMode,
  AvatarPresetConfig,
  VoiceInteractionConfig,
} from "../webview-src/types";

const DEFAULT_AVATAR_MODE: AvatarMode = "vrm";

/**
 * 读取 Webview 页面中注入的数字人配置。
 */
export function readAvatarConfig(): AvatarConfig {
  const jsonElement = document.getElementById("code-agent-avatar-config");
  if (jsonElement?.textContent) {
    try {
      const parsed = JSON.parse(jsonElement.textContent) as Partial<AvatarConfig>;
      return {
        enabled: parsed.enabled !== false,
        mode: normalizeAvatarMode(parsed.mode),
        avatarUri: parsed.avatarUri || undefined,
        vrmUri: parsed.vrmUri || undefined,
        defaultPresetId: parsed.defaultPresetId || parsed.presets?.[0]?.id,
        presets: normalizePresets(parsed.presets),
      };
    } catch (error) {
      console.error("[Code Agent] Failed to parse avatar config.", error);
    }
  }

  return {
    enabled: true,
    mode: DEFAULT_AVATAR_MODE,
    presets: [],
  };
}

/**
 * 读取 Webview 页面中注入的语音交互配置。
 */
export function readVoiceInteractionConfig(): VoiceInteractionConfig {
  const jsonElement = document.getElementById("code-agent-voice-config");
  if (jsonElement?.textContent) {
    try {
      const parsed = JSON.parse(jsonElement.textContent) as Partial<VoiceInteractionConfig>;
      return {
        enabled: parsed.enabled !== false,
        baseUrl: parsed.baseUrl?.trim() || "http://127.0.0.1:3000",
        apiKey: parsed.apiKey?.trim() || "",
        model: parsed.model?.trim() || "whisper-1",
        language: parsed.language?.trim() || "zh",
        autoSubmit: parsed.autoSubmit !== false,
        autoSpeakReplies: parsed.autoSpeakReplies !== false,
      };
    } catch (error) {
      console.error("[Code Agent] Failed to parse voice config.", error);
    }
  }

  return {
    enabled: true,
    baseUrl: "http://127.0.0.1:3000",
    apiKey: "",
    model: "whisper-1",
    language: "zh",
    autoSubmit: true,
    autoSpeakReplies: true,
  };
}

/**
 * 将外部模式值约束到当前支持的数字人模式枚举中。
 */
function normalizeAvatarMode(mode?: string): AvatarMode {
  if (mode === "vrm" || mode === "airi-ready") {
    return mode;
  }

  return DEFAULT_AVATAR_MODE;
}

/**
 * 规范化可切换的数字人预设列表。
 */
function normalizePresets(source?: Partial<AvatarPresetConfig>[]): AvatarPresetConfig[] {
  if (!source?.length) {
    return [];
  }

  return source
    .filter((preset): preset is Partial<AvatarPresetConfig> & { id: string; label: string } => (
      Boolean(preset?.id && preset?.label)
    ))
    .map((preset) => ({
      id: preset.id,
      label: preset.label,
      avatarUri: preset.avatarUri || undefined,
      vrmUri: preset.vrmUri || undefined,
    }));
}
