from fastapi import FastAPI, Query
from fastapi.responses import StreamingResponse

from backend.models import (
    GenerateRequest,
    GenerateResponse,
    TestAnalysisRequest,
    TestAnalysisResponse,
    VoiceBridgeStartRequest,
    VoiceBridgeStartResponse,
    VoiceBridgeTranscriptResponse,
)
from backend.service import CodingAgentService
from backend.voice_bridge import VoiceBridgeError

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


@app.post("/analyze-test-report", response_model=TestAnalysisResponse)
def analyze_test_report(request: TestAnalysisRequest) -> TestAnalysisResponse:
    return service.analyze_test_report(request)


@app.get("/memory")
def inspect_memory(
    workspaceRoot: str = Query(default="", description="Optional workspace root used to filter memory rows."),
    limit: int = Query(default=20, ge=1, le=100, description="Maximum rows per memory section."),
) -> dict[str, object]:
    """
    查看 SQLite 历史对话、长期记忆和上下文选择事件。
    """

    return service.inspect_memory(workspaceRoot, limit)


@app.delete("/memory")
def clear_memory(
    workspaceRoot: str = Query(default="", description="Optional workspace root used to clear only one workspace."),
) -> dict[str, object]:
    """
    清空 SQLite 记忆库；传入 workspaceRoot 时只清空对应工作区。
    """

    return service.clear_memory(workspaceRoot)


@app.post("/voice-bridge/start", response_model=VoiceBridgeStartResponse)
def start_voice_bridge(request: VoiceBridgeStartRequest) -> VoiceBridgeStartResponse:
    try:
        session_id, message = service.start_voice_bridge_session(
            base_url=request.baseUrl,
            api_key=request.apiKey,
            model=request.model,
            language=request.language,
            sample_rate=request.sampleRate,
            channels=request.channels,
        )
        return VoiceBridgeStartResponse(
            sessionId=session_id,
            status="listening",
            message=message,
        )
    except VoiceBridgeError as exc:
        return VoiceBridgeStartResponse(
            sessionId="",
            status="error",
            message=str(exc),
        )


@app.get("/voice-bridge/{session_id}/interim", response_model=VoiceBridgeTranscriptResponse)
def get_voice_bridge_interim(session_id: str) -> VoiceBridgeTranscriptResponse:
    try:
        transcript = service.get_voice_bridge_interim_transcript(session_id)
        return VoiceBridgeTranscriptResponse(
            sessionId=session_id,
            status="listening",
            text=transcript,
            message="正在通过本地 Python 录音桥接进行实时转写。",
        )
    except VoiceBridgeError as exc:
        return VoiceBridgeTranscriptResponse(
            sessionId=session_id,
            status="error",
            text="",
            message=str(exc),
        )


@app.post("/voice-bridge/{session_id}/stop", response_model=VoiceBridgeTranscriptResponse)
def stop_voice_bridge(session_id: str) -> VoiceBridgeTranscriptResponse:
    try:
        transcript = service.stop_voice_bridge_session(session_id)
        return VoiceBridgeTranscriptResponse(
            sessionId=session_id,
            status="ready",
            text=transcript,
            message="本地录音桥接已结束，最终转写结果已返回。",
        )
    except VoiceBridgeError as exc:
        return VoiceBridgeTranscriptResponse(
            sessionId=session_id,
            status="error",
            text="",
            message=str(exc),
        )
