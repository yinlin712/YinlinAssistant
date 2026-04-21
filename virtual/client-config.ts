import type { AvatarConfig, AvatarMode, AvatarPresetConfig } from "../webview-src/types";

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
