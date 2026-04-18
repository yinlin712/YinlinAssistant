from fastapi import FastAPI
from fastapi.responses import StreamingResponse

from backend.models import GenerateRequest, GenerateResponse
from backend.service import CodingAgentService

# 文件说明：
# 本文件是 Python 后端的 HTTP 入口。
# VS Code 插件只需要调用这里暴露的接口，不必直接感知 Ollama、提示词或动作规划细节。

app = FastAPI(title="Code Agent Backend", version="0.3.0")
service = CodingAgentService()


# 接口说明：
# 用于确认后端进程是否已经正常启动。
@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "provider": "ollama",
        "model_profile": service.ollama.get_profile_name(),
        "configured_model": service.ollama.get_configured_model(),
        "active_model": service.ollama.get_active_model(),
        "base_model": service.ollama.get_base_model(),
        "profile_description": service.ollama.get_profile_description(),
        "adapter_path": service.ollama.get_adapter_path(),
        "modelfile_path": service.ollama.get_modelfile_path(),
        "train_data_dir": service.ollama.get_train_data_dir(),
        "eval_data_dir": service.ollama.get_eval_data_dir(),
    }


# 接口说明：
# 接收插件端传来的用户请求与编辑器上下文，并返回统一的 Agent 响应结构。
@app.post("/generate", response_model=GenerateResponse)
def generate(request: GenerateRequest) -> GenerateResponse:
    return service.generate(request)


# 接口说明：
# 为当前文件改写等场景提供流式事件输出，用于前端实时展示 patch 预览。
@app.post("/stream-generate")
def stream_generate(request: GenerateRequest) -> StreamingResponse:
    return StreamingResponse(
        service.stream_generate(request),
        media_type="application/x-ndjson",
    )
