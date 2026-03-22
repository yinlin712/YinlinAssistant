import json
import os
from typing import Any
from urllib import request
from urllib.error import HTTPError, URLError

"""
负责和本地 Ollama 服务通信。

将来换成 vLLM、LM Studio或LoRA服务，只需要替换这里，而不需要修改整个后端。
"""
class OllamaClient:
    

    def __init__(self) -> None:
        self.base_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
        self.model = os.getenv("OLLAMA_MODEL", "deepseek-r1:7b")

    def chat(self, system_prompt: str, user_prompt: str) -> str:
        body = {
            "model": self.model,
            "stream": False,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
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
            raise RuntimeError(f"Ollama returned HTTP {exc.code}") from exc
        except URLError as exc:
            raise RuntimeError(f"Cannot reach Ollama at {self.base_url}") from exc

        message = data.get("message", {})
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("Ollama returned an empty message")
        return content.strip()
