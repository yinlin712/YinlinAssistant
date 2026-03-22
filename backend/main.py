from fastapi import FastAPI

from backend.models import GenerateRequest, GenerateResponse
from backend.service import CodingAgentService

# 文件说明：
# 本文件是 Python 后端的 HTTP 入口。
# VS Code 插件只需要调用这里暴露的接口，不必直接感知 Ollama、提示词或动作规划细节。

app = FastAPI(title="Vibe Coding Agent Backend", version="0.3.0")
service = CodingAgentService()


# 接口说明：
# 用于确认后端进程是否已经正常启动。
@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "provider": "ollama",
    }


# 接口说明：
# 接收插件端传来的用户请求与编辑器上下文，并返回统一的 Agent 响应结构。
@app.post("/generate", response_model=GenerateResponse)
def generate(request: GenerateRequest) -> GenerateResponse:
    return service.generate(request)
