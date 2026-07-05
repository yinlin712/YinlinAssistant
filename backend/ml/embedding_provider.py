from __future__ import annotations

import hashlib
import json
import math
import os
import re
from dataclasses import dataclass
from typing import Literal
from urllib import request
from urllib.error import HTTPError, URLError

import numpy as np


EmbeddingProviderName = Literal["hashing", "ollama", "auto"]
DEFAULT_OLLAMA_EMBEDDING_MODEL = "bge-m3"

ASCII_TOKEN_PATTERN = re.compile(r"[a-zA-Z_][a-zA-Z0-9_./-]{1,}")
CJK_TOKEN_PATTERN = re.compile(r"[\u4e00-\u9fff]{2,}")

STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "that",
    "this",
    "from",
    "into",
    "please",
    "help",
    "project",
    "workspace",
    "file",
    "files",
    "code",
    "agent",
    "当前",
    "这个",
    "那个",
    "一个",
    "帮我",
    "请你",
    "需要",
    "项目",
    "工程",
    "文件",
    "代码",
}

DOMAIN_ALIASES = {
    "报表": ["report", "format", "summary"],
    "报告": ["report", "summary"],
    "平均分": ["average", "avg", "score"],
    "成绩": ["score", "student", "record"],
    "学生": ["student", "record"],
    "数据": ["data", "record", "json"],
    "加载": ["load", "read", "storage", "path"],
    "读取": ["read", "load", "json", "storage"],
    "保存": ["save", "write", "storage"],
    "存储": ["storage", "json", "path"],
    "模型": ["model", "record", "entity"],
    "管理": ["manager", "service"],
    "统计": ["report", "summary", "average"],
    "封装": ["extract", "helper", "function", "refactor"],
    "重构": ["refactor", "extract", "structure"],
    "注释": ["comment", "docstring", "documentation"],
    "上下文": ["context", "memory", "history"],
    "记忆": ["memory", "history", "preference"],
}


@dataclass(frozen=True)
class EmbeddingConfig:
    """
    定义文本向量化模块的运行配置。
    """

    provider: EmbeddingProviderName = "auto"
    model: str = DEFAULT_OLLAMA_EMBEDDING_MODEL
    base_url: str = "http://127.0.0.1:11434"
    vector_size: int = 256
    timeout_seconds: float = 12.0


@dataclass(frozen=True)
class EmbeddingResult:
    """
    保存一次批量文本向量化的结果和实际使用的提供方信息。
    """

    vectors: np.ndarray
    provider_name: str
    model_name: str
    fallback_used: bool = False
    warning: str = ""


class HashingEmbeddingProvider:
    """
    使用特征哈希生成稳定文本向量，作为无外部模型依赖的本地回退方案。
    """

    def __init__(self, vector_size: int = 256) -> None:
        self.vector_size = vector_size

    def embed_texts(self, texts: list[str]) -> EmbeddingResult:
        vectors = np.vstack([self._embed(text) for text in texts])
        return EmbeddingResult(
            vectors=vectors,
            provider_name="hashing",
            model_name=f"feature-hashing-{self.vector_size}",
        )

    def _embed(self, text: str) -> np.ndarray:
        vector = np.zeros(self.vector_size, dtype=np.float64)
        tokens = self._tokenize(text)
        if not tokens:
            return vector

        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8", errors="ignore")).digest()
            bucket = int.from_bytes(digest[:8], "big") % self.vector_size
            sign = 1.0 if digest[8] % 2 == 0 else -1.0
            vector[bucket] += sign

        return normalize_vector(vector)

    def _tokenize(self, text: str) -> list[str]:
        normalized = text.lower()
        tokens: list[str] = []

        for token in ASCII_TOKEN_PATTERN.findall(normalized):
            tokens.append(token)
            tokens.extend(piece for piece in re.split(r"[./_-]+", token) if len(piece) >= 2)

        for segment in CJK_TOKEN_PATTERN.findall(normalized):
            tokens.append(segment)
            tokens.extend(build_cjk_ngrams(segment))

        expanded = list(tokens)
        for token in tokens:
            expanded.extend(expand_domain_aliases(token))

        return [token for token in expanded if len(token) >= 2 and token not in STOPWORDS]


class OllamaEmbeddingProvider:
    """
    调用 Ollama 兼容的 embedding 接口，适配 bge-m3、nomic-embed-text 等本地向量模型。
    """

    def __init__(self, config: EmbeddingConfig) -> None:
        self.config = config

    def embed_texts(self, texts: list[str]) -> EmbeddingResult:
        if not self.config.model.strip():
            raise RuntimeError("Ollama embedding model is not configured")

        try:
            vectors = self._embed_with_batch_api(texts)
        except RuntimeError:
            vectors = self._embed_with_legacy_api(texts)

        return EmbeddingResult(
            vectors=normalize_matrix(vectors),
            provider_name="ollama",
            model_name=self.config.model,
        )

    def _embed_with_batch_api(self, texts: list[str]) -> np.ndarray:
        body = {
            "model": self.config.model,
            "input": texts,
        }
        data = self._post_json("/api/embed", body)
        embeddings = data.get("embeddings")
        if not isinstance(embeddings, list) or len(embeddings) != len(texts):
            raise RuntimeError("Ollama /api/embed returned invalid embeddings")

        return np.asarray(embeddings, dtype=np.float64)

    def _embed_with_legacy_api(self, texts: list[str]) -> np.ndarray:
        vectors: list[list[float]] = []
        for text in texts:
            data = self._post_json(
                "/api/embeddings",
                {
                    "model": self.config.model,
                    "prompt": text,
                },
            )
            embedding = data.get("embedding")
            if not isinstance(embedding, list):
                raise RuntimeError("Ollama /api/embeddings returned invalid embedding")
            vectors.append(embedding)

        return np.asarray(vectors, dtype=np.float64)

    def _post_json(self, path: str, body: dict[str, object]) -> dict[str, object]:
        payload = json.dumps(body).encode("utf-8")
        req = request.Request(
            url=f"{self.config.base_url.rstrip('/')}{path}",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with request.urlopen(req, timeout=self.config.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = read_http_error_body(exc)
            raise RuntimeError(f"Ollama embedding HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise RuntimeError(f"Cannot reach Ollama embedding service at {self.config.base_url}") from exc


class HybridEmbeddingProvider:
    """
    在可用时使用 Ollama embedding 模型，不可用时退回到特征哈希向量。
    """

    def __init__(self, config: EmbeddingConfig) -> None:
        self.config = config
        self.hashing_provider = HashingEmbeddingProvider(config.vector_size)

    def embed_texts(self, texts: list[str]) -> EmbeddingResult:
        if not texts:
            return EmbeddingResult(
                vectors=np.empty((0, self.config.vector_size), dtype=np.float64),
                provider_name="hashing",
                model_name=f"feature-hashing-{self.config.vector_size}",
            )

        should_try_ollama = self.config.provider == "ollama" or (
            self.config.provider == "auto" and bool(self.config.model.strip())
        )
        if not should_try_ollama:
            return self.hashing_provider.embed_texts(texts)

        try:
            return OllamaEmbeddingProvider(self.config).embed_texts(texts)
        except Exception as exc:
            fallback = self.hashing_provider.embed_texts(texts)
            return EmbeddingResult(
                vectors=fallback.vectors,
                provider_name=fallback.provider_name,
                model_name=fallback.model_name,
                fallback_used=True,
                warning=str(exc),
            )


def build_embedding_provider_from_env() -> HybridEmbeddingProvider:
    """
    从环境变量创建 embedding 提供方，便于在演示环境和真实向量模型之间切换。
    """

    provider = os.getenv("CODE_AGENT_EMBEDDING_PROVIDER", "auto").strip().lower()
    if provider not in {"auto", "hashing", "ollama"}:
        provider = "auto"

    vector_size = parse_positive_int(os.getenv("CODE_AGENT_EMBEDDING_VECTOR_SIZE"), 256)
    timeout_seconds = parse_positive_float(os.getenv("CODE_AGENT_EMBEDDING_TIMEOUT"), 12.0)

    config = EmbeddingConfig(
        provider=provider,  # type: ignore[arg-type]
        model=os.getenv("CODE_AGENT_EMBEDDING_MODEL", DEFAULT_OLLAMA_EMBEDDING_MODEL).strip(),
        base_url=os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").strip(),
        vector_size=vector_size,
        timeout_seconds=timeout_seconds,
    )
    return HybridEmbeddingProvider(config)


def build_cjk_ngrams(segment: str) -> list[str]:
    """
    将连续中文片段切成 2-gram 和 3-gram，增强中文短语匹配能力。
    """

    if len(segment) <= 2:
        return [segment]

    grams: list[str] = []
    for size in (2, 3):
        if len(segment) < size:
            continue
        for index in range(0, len(segment) - size + 1):
            grams.append(segment[index : index + size])
    return grams


def expand_domain_aliases(token: str) -> list[str]:
    """
    将中文领域词扩展为常见代码标识符，提高中英文混合项目中的召回稳定性。
    """

    expanded: list[str] = []
    for source, aliases in DOMAIN_ALIASES.items():
        if source in token:
            expanded.extend(aliases)
    return expanded


def normalize_vector(vector: np.ndarray) -> np.ndarray:
    """
    对单个向量做 L2 归一化，避免文本长度直接支配相似度。
    """

    norm = np.linalg.norm(vector)
    if norm <= 0:
        return vector
    return vector / norm


def normalize_matrix(matrix: np.ndarray) -> np.ndarray:
    """
    对二维向量矩阵逐行归一化。
    """

    if matrix.size == 0:
        return matrix

    normalized = matrix.astype(np.float64, copy=True)
    for index in range(normalized.shape[0]):
        normalized[index] = normalize_vector(normalized[index])
    return normalized


def parse_positive_int(raw_value: str | None, fallback: int) -> int:
    """
    解析正整数环境变量，解析失败时返回默认值。
    """

    try:
        value = int(raw_value or "")
    except ValueError:
        return fallback
    return value if value > 0 else fallback


def parse_positive_float(raw_value: str | None, fallback: float) -> float:
    """
    解析正浮点数环境变量，解析失败时返回默认值。
    """

    try:
        value = float(raw_value or "")
    except ValueError:
        return fallback
    return value if value > 0 else fallback


def read_http_error_body(error: HTTPError) -> str:
    """
    读取 HTTP 错误响应体，便于定位本地 embedding 服务异常。
    """

    try:
        return error.read().decode("utf-8").strip()
    except Exception:
        return ""
