from fastapi import FastAPI

from backend.models import GenerateRequest, GenerateResponse
from backend.service import CodingAgentService

# FastAPI 应用是Python后端的统一入口。
# VS Code 插件只需要调用暴露的HTTP接口，封装Ollama细节。
app = FastAPI(title="Vibe Coding Agent Backend", version="0.3.0")
service = CodingAgentService()


@app.get("/health")
def health() -> dict[str, str]:
    # 确认后端服务是否正常启动。
    return {
        "status": "ok", 
        "provider": "ollama"
        }


@app.post("/generate", response_model=GenerateResponse)
def generate(request: GenerateRequest) -> GenerateResponse:
    # 接收插件发送来的问题和编辑器上下文，并返回模型回答。
    return service.generate(request)
