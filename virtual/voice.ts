export interface BrowserSpeechRecognitionResultItem {
  transcript: string;
  isFinal: boolean;
}

export interface BrowserSpeechRecognitionLike {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  maxAlternatives: number;
  onresult: ((event: { resultIndex: number; results: ArrayLike<ArrayLike<{ transcript: string }> & { isFinal?: boolean }> }) => void) | null;
  onerror: ((event: { error?: string }) => void) | null;
  onend: (() => void) | null;
  start(): void;
  stop(): void;
  abort(): void;
}

/**
 * 判断当前 Webview 是否支持麦克风录音能力。
 */
export function isVoiceRecordingSupported(): boolean {
  return typeof navigator !== "undefined"
    && Boolean(navigator.mediaDevices?.getUserMedia)
    && typeof MediaRecorder !== "undefined";
}

/**
 * 判断当前 Webview 是否支持浏览器原生实时语音识别。
 */
export function isBrowserSpeechRecognitionSupported(): boolean {
  if (typeof window === "undefined") {
    return false;
  }

  const speechWindow = window as Window & {
    SpeechRecognition?: new () => BrowserSpeechRecognitionLike;
    webkitSpeechRecognition?: new () => BrowserSpeechRecognitionLike;
  };

  return Boolean(speechWindow.SpeechRecognition || speechWindow.webkitSpeechRecognition);
}

/**
 * 创建一个浏览器原生语音识别实例，用于实时回填识别文本。
 */
export function createBrowserSpeechRecognition(language?: string): BrowserSpeechRecognitionLike | null {
  if (typeof window === "undefined") {
    return null;
  }

  const speechWindow = window as Window & {
    SpeechRecognition?: new () => BrowserSpeechRecognitionLike;
    webkitSpeechRecognition?: new () => BrowserSpeechRecognitionLike;
  };

  const RecognitionConstructor = speechWindow.SpeechRecognition || speechWindow.webkitSpeechRecognition;
  if (!RecognitionConstructor) {
    return null;
  }

  const recognition = new RecognitionConstructor();
  recognition.continuous = true;
  recognition.interimResults = true;
  recognition.maxAlternatives = 1;
  recognition.lang = normalizeSpeechLanguage(language);
  return recognition;
}

/**
 * 选择当前浏览器环境下更稳定的录音 MIME 类型。
 */
export function resolvePreferredRecordingMimeType(): string {
  if (typeof MediaRecorder === "undefined" || typeof MediaRecorder.isTypeSupported !== "function") {
    return "audio/webm";
  }

  const candidates = [
    "audio/webm;codecs=opus",
    "audio/webm",
    "audio/mp4",
    "audio/ogg;codecs=opus",
    "audio/ogg",
  ];

  return candidates.find((item) => MediaRecorder.isTypeSupported(item)) || "audio/webm";
}

/**
 * 将录音 Blob 转为 base64 文本，便于通过 VS Code Webview 消息通道发送。
 */
export async function blobToBase64(blob: Blob): Promise<string> {
  const arrayBuffer = await blob.arrayBuffer();
  const bytes = new Uint8Array(arrayBuffer);
  const chunkSize = 0x8000;
  let binary = "";

  for (let index = 0; index < bytes.length; index += chunkSize) {
    const chunk = bytes.subarray(index, index + chunkSize);
    binary += String.fromCharCode(...chunk);
  }

  return btoa(binary);
}

/**
 * 从浏览器 SpeechRecognition 结果中提取“已确认文本”和“临时文本”。
 */
export function extractBrowserRecognitionText(event: {
  resultIndex: number;
  results: ArrayLike<ArrayLike<{ transcript: string }> & { isFinal?: boolean }>;
}): { committedText: string; interimText: string } {
  const committed: string[] = [];
  const interim: string[] = [];

  for (let index = event.resultIndex; index < event.results.length; index += 1) {
    const result = event.results[index];
    const transcript = result?.[0]?.transcript?.trim() || "";
    if (!transcript) {
      continue;
    }

    if (result.isFinal) {
      committed.push(transcript);
    } else {
      interim.push(transcript);
    }
  }

  return {
    committedText: committed.join(""),
    interimText: interim.join(""),
  };
}

/**
 * 使用浏览器内置语音合成播报数字人回复。
 */
export function speakAvatarText(text: string): void {
  if (!text.trim() || typeof window === "undefined" || !("speechSynthesis" in window)) {
    return;
  }

  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = "zh-CN";
  utterance.rate = 1;
  utterance.pitch = 1.02;

  try {
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(utterance);
  } catch (error) {
    console.warn("[Code Agent] Failed to speak avatar reply.", error);
  }
}

/**
 * 将简写语言值规整为更适合浏览器识别的地区化标签。
 */
export function normalizeSpeechLanguage(language?: string): string {
  const normalized = (language || "").trim().toLowerCase();
  if (!normalized) {
    return "zh-CN";
  }

  if (normalized === "zh") {
    return "zh-CN";
  }

  if (normalized === "en") {
    return "en-US";
  }

  return language!;
}
