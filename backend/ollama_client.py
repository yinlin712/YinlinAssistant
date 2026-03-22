import json
import os
from typing import Any
from urllib import request
from urllib.error import HTTPError, URLError

# 文件说明：
# 本文件负责与本地 Ollama 服务通信。
# 如果未来接入 LoRA 微调模型或其他推理服务，优先替换这里，而不是改动整个后端链路。


# 类说明：
# 封装一次完整的 Ollama 聊天请求。
class OllamaClient:
    # 方法说明：
    # 从环境变量读取服务地址、模型名和生成参数。
    def __init__(self) -> None:
        self.base_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
        self.model = os.getenv("OLLAMA_MODEL", "deepseek-r1:7b")
        self.temperature = float(os.getenv("OLLAMA_TEMPERATURE", "0"))
        self.seed = int(os.getenv("OLLAMA_SEED", "42"))

    # 方法说明：
    # 向 Ollama 发送一次非流式聊天请求，并返回文本结果。
    def chat(self, system_prompt: str, user_prompt: str) -> str:
        body = {
            "model": self.model,
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
            raise RuntimeError(f"Ollama returned HTTP {exc.code}") from exc
        except URLError as exc:
            raise RuntimeError(f"Cannot reach Ollama at {self.base_url}") from exc

        message = data.get("message", {})
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("Ollama returned an empty message")

        return content.strip()
