import json
import os
from collections.abc import Iterator
from typing import Any
from urllib import request
from urllib.error import HTTPError, URLError

from backend.model_settings import ResolvedModelSettings, resolve_model_settings

# 文件说明：
# 本文件负责与本机 Ollama 服务通信。
# 模型选择统一来自模型档案与环境变量，便于后续切换到 LoRA 适配器导出的模型别名。


class OllamaClient:
    """
    封装 Ollama 聊天接口与流式接口，并在主模型不可用时自动尝试备用模型。
    """

    def __init__(self) -> None:
        self.base_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
        self.settings: ResolvedModelSettings = resolve_model_settings()
        self.model = self.settings.configured_model
        self.fallback_model = self.settings.fallback_model
        self.temperature = float(os.getenv("OLLAMA_TEMPERATURE", "0"))
        self.seed = int(os.getenv("OLLAMA_SEED", "42"))
        self.active_model = self.model

    def get_configured_model(self) -> str:
        return self.model

    def get_active_model(self) -> str:
        return self.active_model

    def get_profile_name(self) -> str:
        return self.settings.profile_name

    def get_base_model(self) -> str:
        return self.settings.base_model

    def get_profile_description(self) -> str:
        return self.settings.description

    def get_adapter_path(self) -> str:
        return self.settings.adapter_path

    def get_modelfile_path(self) -> str:
        return self.settings.modelfile_path

    def get_train_data_dir(self) -> str:
        return self.settings.train_data_dir

    def get_eval_data_dir(self) -> str:
        return self.settings.eval_data_dir

    def chat(self, system_prompt: str, user_prompt: str) -> str:
        primary_error: RuntimeError | None = None

        try:
            content = self._chat_once(self.model, system_prompt, user_prompt)
            self.active_model = self.model
            return content
        except RuntimeError as exc:
            primary_error = exc
            if not self._should_try_fallback(exc):
                raise

        fallback_model = self._resolve_fallback_model()
        if fallback_model is None:
            raise primary_error or RuntimeError("Ollama request failed")

        content = self._chat_once(fallback_model, system_prompt, user_prompt)
        self.active_model = fallback_model
        return content

    def stream_chat(self, system_prompt: str, user_prompt: str) -> Iterator[str]:
        primary_error: RuntimeError | None = None

        try:
            self.active_model = self.model
            yield from self._stream_chat_once(self.model, system_prompt, user_prompt)
            return
        except RuntimeError as exc:
            primary_error = exc
            if not self._should_try_fallback(exc):
                raise

        fallback_model = self._resolve_fallback_model()
        if fallback_model is None:
            raise primary_error or RuntimeError("Ollama request failed")

        self.active_model = fallback_model
        yield from self._stream_chat_once(fallback_model, system_prompt, user_prompt)

    def _chat_once(self, model: str, system_prompt: str, user_prompt: str) -> str:
        body = {
            "model": model,
            "stream": False,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "options": {
                "temperature": self.temperature,
                "seed": self.seed,
            },
        }

        payload = json.dumps(body).encode("utf-8")
        req = request.Request(
            url=f"{self.base_url}/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with request.urlopen(req, timeout=180) as response:
                data: dict[str, Any] = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            error_body = self._read_http_error_body(exc)
            if error_body:
                raise RuntimeError(f"Ollama returned HTTP {exc.code}: {error_body}") from exc
            raise RuntimeError(f"Ollama returned HTTP {exc.code}") from exc
        except URLError as exc:
            raise RuntimeError(f"Cannot reach Ollama at {self.base_url}") from exc

        message = data.get("message", {})
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("Ollama returned an empty message")

        return content.strip()

    def _stream_chat_once(self, model: str, system_prompt: str, user_prompt: str) -> Iterator[str]:
        body = {
            "model": model,
            "stream": True,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "options": {
                "temperature": self.temperature,
                "seed": self.seed,
            },
        }

        payload = json.dumps(body).encode("utf-8")
        req = request.Request(
            url=f"{self.base_url}/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with request.urlopen(req, timeout=180) as response:
                for raw_line in response:
                    line = raw_line.decode("utf-8").strip()
                    if not line:
                        continue

                    data: dict[str, Any] = json.loads(line)
                    message = data.get("message", {})
                    content = message.get("content")
                    if isinstance(content, str) and content:
                        yield content
        except HTTPError as exc:
            error_body = self._read_http_error_body(exc)
            if error_body:
                raise RuntimeError(f"Ollama returned HTTP {exc.code}: {error_body}") from exc
            raise RuntimeError(f"Ollama returned HTTP {exc.code}") from exc
        except URLError as exc:
            raise RuntimeError(f"Cannot reach Ollama at {self.base_url}") from exc

    def _should_try_fallback(self, error: RuntimeError) -> bool:
        message = str(error).lower()
        return "not found" in message or "manifest" in message

    def _resolve_fallback_model(self) -> str | None:
        fallback_model = self.fallback_model.strip()
        if not fallback_model or fallback_model == self.model:
            return None
        return fallback_model

    def _read_http_error_body(self, error: HTTPError) -> str:
        try:
            return error.read().decode("utf-8").strip()
        except Exception:
            return ""
