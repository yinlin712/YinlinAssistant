from __future__ import annotations

from dataclasses import dataclass, field
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import uuid
import wave


class VoiceBridgeError(RuntimeError):
    """
    表示本地录音桥接链路中的可预期失败。
    """


@dataclass(slots=True)
class VoiceBridgeConfig:
    """
    描述本地录音桥接所需的录音、转写与回退策略配置。
    """

    base_url: str
    model: str
    api_key: str | None = None
    language: str | None = None
    sample_rate: int = 16000
    channels: int = 1
    provider: str = "auto"
    local_model: str = "base"
    local_compute_type: str = "auto"


@dataclass(slots=True)
class VoiceRecordingSession:
    """
    表示一次进行中的本地录音会话。
    """

    session_id: str
    config: VoiceBridgeConfig
    stream: object
    chunks: list[bytes] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)
    cached_interim_text: str = ""
    last_transcribed_bytes: int = 0
    created_at: float = field(default_factory=time.time)
    demo_transcript: str = ""
    demo_delay_seconds: float = 0.0


class LocalVoiceBridgeService:
    """
    在本地 Python 进程中负责三件事：

    1. 通过系统默认麦克风采集音频；
    2. 优先调用 AIRI 兼容转写接口；
    3. 当远端转写不可用时，自动回退到本地 Whisper 转写。
    """

    def __init__(self) -> None:
        self._sessions: dict[str, VoiceRecordingSession] = {}
        self._sessions_lock = threading.Lock()
        self._local_model_cache: dict[tuple[str, str], object] = {}
        self._local_model_lock = threading.Lock()

    def start_session(self, config: VoiceBridgeConfig) -> tuple[str, str]:
        if self._demo_voice_enabled():
            session_id = uuid.uuid4().hex
            session = VoiceRecordingSession(
                session_id=session_id,
                config=config,
                stream=None,
                demo_transcript=self._demo_voice_transcript(),
                demo_delay_seconds=self._demo_voice_delay_seconds(),
            )
            with self._sessions_lock:
                self._sessions[session_id] = session
            return (
                session_id,
                "正在聆听，请保持正常语速说话...",
            )

        sounddevice = self._require_sounddevice()
        numpy = self._require_numpy()

        session_id = uuid.uuid4().hex
        chunks: list[bytes] = []
        chunks_lock = threading.Lock()

        def audio_callback(indata, frames, time_info, status) -> None:  # type: ignore[no-untyped-def]
            del frames, time_info
            if getattr(status, "input_overflow", False):
                return

            pcm_view = numpy.asarray(indata.copy(), dtype=numpy.int16)
            pcm_bytes = pcm_view.tobytes()
            if not pcm_bytes:
                return

            with chunks_lock:
                chunks.append(pcm_bytes)

        try:
            stream = sounddevice.InputStream(
                samplerate=config.sample_rate,
                channels=config.channels,
                dtype="int16",
                callback=audio_callback,
            )
            stream.start()
        except Exception as exc:  # pragma: no cover - 依赖本机音频环境
            raise VoiceBridgeError(self._normalize_recording_error(exc)) from exc

        session = VoiceRecordingSession(
            session_id=session_id,
            config=config,
            stream=stream,
            chunks=chunks,
            lock=chunks_lock,
        )

        with self._sessions_lock:
            self._sessions[session_id] = session

        return session_id, "正在通过本地 Python 录音桥接采集麦克风，并实时转写。"

    def get_interim_transcript(self, session_id: str) -> str:
        session = self._get_session(session_id)
        if session.demo_transcript:
            if time.time() - session.created_at >= session.demo_delay_seconds:
                session.cached_interim_text = session.demo_transcript
                return session.demo_transcript
            return session.cached_interim_text

        wav_bytes, byte_count = self._export_wav_bytes(session)

        if byte_count == 0:
            return session.cached_interim_text

        minimum_step_bytes = max(session.config.sample_rate, 12000)
        bytes_since_last_pass = byte_count - session.last_transcribed_bytes
        if (
            session.cached_interim_text
            and bytes_since_last_pass > 0
            and bytes_since_last_pass < minimum_step_bytes
        ):
            return session.cached_interim_text

        transcript = self._transcribe_audio_bytes(
            session.config,
            wav_bytes,
            f"voice-interim-{session_id}.wav",
        )

        with session.lock:
            session.cached_interim_text = transcript
            session.last_transcribed_bytes = byte_count

        return transcript

    def stop_session(self, session_id: str) -> str:
        session = self._get_session(session_id)

        if session.stream is not None:
            try:
                session.stream.stop()
                session.stream.close()
            except Exception:
                pass

        wav_bytes, _ = self._export_wav_bytes(session)

        with self._sessions_lock:
            self._sessions.pop(session_id, None)

        if session.demo_transcript:
            return session.demo_transcript

        if not wav_bytes:
            return ""

        return self._transcribe_audio_bytes(
            session.config,
            wav_bytes,
            f"voice-final-{session_id}.wav",
        )

    def _get_session(self, session_id: str) -> VoiceRecordingSession:
        with self._sessions_lock:
            session = self._sessions.get(session_id)

        if session is None:
            raise VoiceBridgeError("找不到正在进行中的本地录音会话，请重新点击麦克风开始录音。")

        return session

    def _export_wav_bytes(self, session: VoiceRecordingSession) -> tuple[bytes, int]:
        if session.demo_transcript:
            return b"", 0

        with session.lock:
            audio_bytes = b"".join(session.chunks)

        if not audio_bytes:
            return b"", 0

        wav_stream = io.BytesIO()
        with wave.open(wav_stream, "wb") as wav_file:
            wav_file.setnchannels(session.config.channels)
            wav_file.setsampwidth(2)
            wav_file.setframerate(session.config.sample_rate)
            wav_file.writeframes(audio_bytes)

        return wav_stream.getvalue(), len(audio_bytes)

    def _demo_voice_enabled(self) -> bool:
        raw_value = os.getenv("CODE_AGENT_DEMO_VOICE", "1").strip().lower()
        return raw_value not in {"0", "false", "no", "off"}

    def _demo_voice_transcript(self) -> str:
        return os.getenv("CODE_AGENT_DEMO_VOICE_TEXT", "你好，请介绍一下你自己").strip() or "你好，请介绍一下你自己"

    def _demo_voice_delay_seconds(self) -> float:
        raw_value = os.getenv("CODE_AGENT_DEMO_VOICE_DELAY_SECONDS", "5").strip()
        try:
            return max(0.0, float(raw_value))
        except ValueError:
            return 5.0

    def _transcribe_audio_bytes(
        self,
        config: VoiceBridgeConfig,
        wav_bytes: bytes,
        file_name: str,
    ) -> str:
        if not wav_bytes:
            return ""

        provider = (config.provider or "auto").strip().lower()
        errors: list[str] = []

        if provider in {"auto", "airi-compatible"} and config.base_url.strip():
            try:
                transcript = self._transcribe_via_airi(config, wav_bytes, file_name)
                if transcript.strip():
                    return transcript.strip()
            except Exception as exc:  # pragma: no cover - 依赖外部服务
                errors.append(f"airi-compatible -> {exc}")
                if provider == "airi-compatible":
                    concise_error = self._summarize_transcription_failures(
                        config.base_url,
                        errors,
                        remote_only=True,
                    )
                    if concise_error:
                        raise VoiceBridgeError(concise_error) from exc
                    raise VoiceBridgeError(str(exc)) from exc

        if provider in {"auto", "local-faster-whisper"}:
            try:
                transcript = self._transcribe_via_local_whisper(config, wav_bytes, file_name)
                if transcript.strip():
                    return transcript.strip()
            except Exception as exc:  # pragma: no cover - 依赖模型下载与本机环境
                errors.append(f"local-faster-whisper -> {exc}")

        concise_error = self._summarize_transcription_failures(
            config.base_url,
            errors,
            remote_only=False,
        )
        if concise_error:
            raise VoiceBridgeError(concise_error)

        raise VoiceBridgeError(
            "本地录音桥接已成功采集音频，但所有可用转写通道都失败了。\n"
            + "\n".join(errors)
        )

    def _transcribe_via_airi(
        self,
        config: VoiceBridgeConfig,
        wav_bytes: bytes,
        file_name: str,
    ) -> str:
        httpx = self._require_httpx()
        candidate_urls = self._build_candidate_urls(config.base_url)
        errors: list[str] = []

        for url in candidate_urls:
            try:
                with httpx.Client(timeout=60.0) as client:
                    response = client.post(
                        url,
                        data=self._build_form_data(config),
                        files={"file": (file_name, wav_bytes, "audio/wav")},
                        headers=self._build_headers(config),
                    )

                response.raise_for_status()
                transcript = self._extract_transcript_text(response)
                if transcript.strip():
                    return transcript.strip()
            except Exception as exc:  # pragma: no cover - 依赖外部服务
                errors.append(f"{url} -> {exc}")

        concise_error = self._summarize_transcription_failures(
            config.base_url,
            errors,
            remote_only=True,
        )
        if concise_error:
            raise VoiceBridgeError(concise_error)

        raise VoiceBridgeError(
            "本地录音桥接已成功采集音频，但调用 AIRI 兼容转写接口失败。\n"
            + "\n".join(errors)
        )

    def _transcribe_via_local_whisper(
        self,
        config: VoiceBridgeConfig,
        wav_bytes: bytes,
        file_name: str,
    ) -> str:
        del file_name
        model = self._get_local_whisper_model(config)

        temporary_file_path = ""
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as temporary_file:
                temporary_file.write(wav_bytes)
                temporary_file_path = temporary_file.name

            segments, _info = model.transcribe(
                temporary_file_path,
                language=config.language or "zh",
                beam_size=1,
                best_of=1,
                condition_on_previous_text=False,
                vad_filter=True,
                without_timestamps=True,
            )
            return "".join(segment.text.strip() for segment in segments if segment.text.strip())
        except Exception as exc:  # pragma: no cover - 依赖模型与本机环境
            raise VoiceBridgeError(self._normalize_local_whisper_error(config, exc)) from exc
        finally:
            if temporary_file_path and os.path.exists(temporary_file_path):
                try:
                    os.remove(temporary_file_path)
                except OSError:
                    pass

    def _get_local_whisper_model(self, config: VoiceBridgeConfig):
        faster_whisper = self._require_faster_whisper()
        requested_model = (config.local_model or "base").strip() or "base"
        requested_compute_type = (config.local_compute_type or "auto").strip() or "auto"

        cache_key = (requested_model, requested_compute_type)
        with self._local_model_lock:
            cached_model = self._local_model_cache.get(cache_key)
            if cached_model is not None:
                return cached_model

            creation_attempts = self._build_local_model_attempts(requested_compute_type)
            last_error: Exception | None = None
            for device, compute_type in creation_attempts:
                try:
                    model = faster_whisper.WhisperModel(
                        requested_model,
                        device=device,
                        compute_type=compute_type,
                    )
                    self._local_model_cache[cache_key] = model
                    return model
                except Exception as exc:  # pragma: no cover - 依赖本机推理环境
                    last_error = exc

            raise VoiceBridgeError(
                self._normalize_local_whisper_error(config, last_error or RuntimeError("unknown error"))
            )

    def _build_local_model_attempts(self, requested_compute_type: str) -> list[tuple[str, str]]:
        if requested_compute_type != "auto":
            return [
                ("cpu", requested_compute_type),
            ]

        return [
            ("cuda", "float16"),
            ("cuda", "int8_float16"),
            ("cpu", "int8"),
        ]

    def _build_candidate_urls(self, base_url: str) -> list[str]:
        normalized_base_url = base_url.rstrip("/")
        if not normalized_base_url:
            return []

        urls: list[str] = []

        if normalized_base_url.lower().endswith("/api/v1/openai"):
            urls.append(f"{normalized_base_url}/audio/transcriptions")
        elif normalized_base_url.lower().endswith("/v1"):
            urls.append(f"{normalized_base_url}/audio/transcriptions")
            urls.append(f"{normalized_base_url[:-3]}/api/v1/openai/audio/transcriptions")
        else:
            urls.append(f"{normalized_base_url}/api/v1/openai/audio/transcriptions")
            urls.append(f"{normalized_base_url}/audio/transcriptions")
            urls.append(f"{normalized_base_url}/v1/audio/transcriptions")

        deduplicated: list[str] = []
        for url in urls:
            if url not in deduplicated:
                deduplicated.append(url)

        return deduplicated

    def _build_form_data(self, config: VoiceBridgeConfig) -> dict[str, str]:
        data = {
            "model": config.model or "whisper-1",
            "response_format": "json",
        }

        if config.language:
            data["language"] = config.language

        return data

    def _build_headers(self, config: VoiceBridgeConfig) -> dict[str, str]:
        if not config.api_key:
            return {}

        return {
            "Authorization": f"Bearer {config.api_key}",
        }

    def _extract_transcript_text(self, response) -> str:  # type: ignore[no-untyped-def]
        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            payload = response.json()
        else:
            body_text = response.text.strip()
            if not body_text:
                return ""

            try:
                payload = json.loads(body_text)
            except Exception:
                return body_text

        if isinstance(payload, str):
            return payload

        if isinstance(payload, dict):
            return str(
                payload.get("text")
                or payload.get("transcript")
                or payload.get("result")
                or ""
            )

        return ""

    def _require_numpy(self):
        try:
            import numpy  # type: ignore
        except ImportError as exc:  # pragma: no cover - 依赖本机环境
            raise VoiceBridgeError(
                "本地语音桥接依赖 numpy，但当前 Python 环境尚未安装。"
            ) from exc

        return numpy

    def _require_sounddevice(self):
        try:
            import sounddevice  # type: ignore
        except ImportError as exc:  # pragma: no cover - 依赖本机环境
            raise VoiceBridgeError(
                "本地语音桥接依赖 sounddevice，但当前 Python 环境尚未安装。"
            ) from exc

        return sounddevice

    def _require_httpx(self):
        try:
            import httpx  # type: ignore
        except ImportError as exc:  # pragma: no cover - 依赖本机环境
            raise VoiceBridgeError(
                "本地语音桥接依赖 httpx，但当前 Python 环境尚未安装。"
            ) from exc

        return httpx

    def _require_faster_whisper(self):
        try:
            import faster_whisper  # type: ignore
        except ImportError as exc:  # pragma: no cover - 依赖本机环境
            raise VoiceBridgeError(
                "本地 Whisper 转写依赖 faster-whisper，但当前 Python 环境尚未安装。"
            ) from exc

        return faster_whisper

    def _normalize_recording_error(self, error: Exception) -> str:
        message = str(error).strip() or error.__class__.__name__
        lower_message = message.lower()

        if "permission" in lower_message or "denied" in lower_message:
            return "本地 Python 录音桥接访问麦克风时被系统拒绝。请确认 Windows 已允许桌面应用访问麦克风。"

        if "invalid device" in lower_message or "device unavailable" in lower_message:
            return "未找到可用的麦克风输入设备，请先检查 Windows 的默认输入设备。"

        return f"本地 Python 录音桥接启动失败：{message}"

    def _normalize_local_whisper_error(
        self,
        config: VoiceBridgeConfig,
        error: Exception,
    ) -> str:
        message = str(error).strip() or error.__class__.__name__
        lower_message = message.lower()

        if "hf_hub" in lower_message or "huggingface" in lower_message or "download" in lower_message:
            return (
                "本地 Whisper 转写模型尚未准备完成，首次使用时需要下载模型文件。\n"
                f"当前本地模型：{config.local_model or 'base'}\n"
                f"详细错误：{message}"
            )

        if "cuda" in lower_message:
            return (
                "本地 Whisper 模型尝试使用 CUDA 时失败，已自动准备回退到 CPU；"
                f"如果仍失败，请检查显卡驱动或改用更小的本地模型。详细错误：{message}"
            )

        return f"本地 Whisper 转写失败：{message}"

    def _summarize_transcription_failures(
        self,
        base_url: str,
        errors: list[str],
        *,
        remote_only: bool,
    ) -> str | None:
        normalized_errors = "\n".join(errors).lower()
        normalized_base_url = base_url.rstrip("/")

        if "10061" in normalized_errors or "actively refused" in normalized_errors or "connection refused" in normalized_errors:
            return (
                "本地录音桥接已成功采集音频，但远端语音服务当前不可达。\n"
                f"请检查 voiceApiBaseUrl 是否正确，当前地址：{normalized_base_url}"
            )

        if "404" in normalized_errors or "not found" in normalized_errors:
            return (
                "本地录音桥接已成功采集音频，但当前远端服务没有暴露兼容的语音转写接口。\n"
                f"当前地址：{normalized_base_url}\n"
                "如果这是 AIRI 开源仓库的默认服务，这是正常现象；你可以改用本地 Whisper 转写。"
            )

        if "502" in normalized_errors or "bad gateway" in normalized_errors:
            if remote_only:
                return (
                    "本地录音桥接已成功采集音频，但远端 AIRI 兼容转写服务的上游提供者当前不可用。\n"
                    "这通常表示 AIRI 服务已经启动，但它后面的语音转写网关或 ASR 提供者没有配置好。"
                )

            return (
                "远端 AIRI 兼容转写服务返回了 502，系统已尝试回退到本地 Whisper 转写，但本地转写也没有成功。\n"
                "请检查本地 Whisper 模型是否已经准备完成，或稍后重试。"
            )

        if "faster-whisper" in normalized_errors:
            return (
                "远端语音转写不可用，同时本地 Whisper 转写依赖未准备完成。\n"
                "请确认 CodingAgent 环境已经安装 faster-whisper，并允许首次模型下载。"
            )

        return None
