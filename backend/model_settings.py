import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# 文件说明：
# 本文件统一管理本地推理模型的配置读取逻辑。
# 运行时优先读取环境变量，其次读取仓库中的模型档案文件，便于后续接入 LoRA 模型别名与适配器目录。

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MODEL_PROFILE_PATH = PROJECT_ROOT / "config" / "model_profiles.json"

DEFAULT_PROFILE_NAME = "qwen_local_default"
DEFAULT_MODEL = "qwen2.5-coder:7b"
DEFAULT_FALLBACK_MODEL = "deepseek-r1:7b"


@dataclass(frozen=True)
class ResolvedModelSettings:
    profile_name: str
    provider: str
    configured_model: str
    fallback_model: str
    base_model: str
    description: str
    adapter_path: str
    modelfile_path: str
    train_data_dir: str
    eval_data_dir: str


# 函数说明：
# 解析仓库中的模型档案文件；若文件缺失，则回退到内置默认配置。
def load_model_profile_document() -> dict[str, Any]:
    if MODEL_PROFILE_PATH.exists():
        return json.loads(MODEL_PROFILE_PATH.read_text(encoding="utf-8"))

    return {
        "default_profile": DEFAULT_PROFILE_NAME,
        "profiles": {
            DEFAULT_PROFILE_NAME: {
                "provider": "ollama",
                "runtime_model": DEFAULT_MODEL,
                "fallback_model": DEFAULT_FALLBACK_MODEL,
                "base_model": "Qwen2.5-Coder-7B-Instruct",
                "description": "默认本地编码模型。",
                "adapter_path": "models/lora/adapters/qwen-coding-agent",
                "modelfile_path": "models/lora/modelfiles/qwen-coding-agent.Modelfile",
                "train_data_dir": "data/lora/train",
                "eval_data_dir": "data/lora/eval",
            }
        },
    }


# 函数说明：
# 将模型档案与环境变量合并为当前运行时实际使用的模型设置。
def resolve_model_settings() -> ResolvedModelSettings:
    document = load_model_profile_document()
    profiles = document.get("profiles", {})
    default_profile_name = str(document.get("default_profile", DEFAULT_PROFILE_NAME))
    requested_profile_name = os.getenv("OLLAMA_MODEL_PROFILE", default_profile_name).strip() or default_profile_name
    active_profile_name = requested_profile_name if requested_profile_name in profiles else default_profile_name
    profile = profiles.get(active_profile_name, {})

    configured_model = os.getenv("OLLAMA_MODEL", str(profile.get("runtime_model", DEFAULT_MODEL))).strip() or DEFAULT_MODEL
    fallback_model = os.getenv(
        "OLLAMA_FALLBACK_MODEL",
        str(profile.get("fallback_model", DEFAULT_FALLBACK_MODEL)),
    ).strip() or DEFAULT_FALLBACK_MODEL

    return ResolvedModelSettings(
        profile_name=active_profile_name,
        provider=str(profile.get("provider", "ollama")),
        configured_model=configured_model,
        fallback_model=fallback_model,
        base_model=str(profile.get("base_model", "")),
        description=str(profile.get("description", "")),
        adapter_path=str(profile.get("adapter_path", "")),
        modelfile_path=str(profile.get("modelfile_path", "")),
        train_data_dir=str(profile.get("train_data_dir", "data/lora/train")),
        eval_data_dir=str(profile.get("eval_data_dir", "data/lora/eval")),
    )
