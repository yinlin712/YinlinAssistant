/**
 * 统一描述插件端与本地 Python 录音桥接共用的语音转写配置。
 * 当前版本不再由 Webview 直接上传音频，而是由 Python 后端负责采集麦克风并调用 AIRI 兼容接口。
 */
export interface VoiceTranscriptionConfig {
  enabled: boolean;
  baseUrl: string;
  apiKey?: string;
  model: string;
  language?: string;
}
