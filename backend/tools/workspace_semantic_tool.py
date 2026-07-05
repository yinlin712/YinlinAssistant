import re
from collections import Counter
from dataclasses import dataclass, field

import numpy as np

from backend.ml.embedding_provider import build_embedding_provider_from_env, normalize_matrix
from backend.models import AgentContextModel
from backend.request_classifier import mentions_documentation
from backend.tools.workspace_search_tool import WorkspaceFileSnapshot, WorkspaceSearchResult

# 文件说明：
# 本文件提供项目级语义检索模块。
# 它复用 backend/ml/embedding_provider.py 中的统一向量化能力，默认优先调用
# Ollama 的 bge-m3 embedding 模型；如果本地模型不可用，则自动回退到哈希向量。

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
    "一下",
    "帮我",
    "请你",
    "需要",
    "项目",
    "工程",
    "文件",
    "代码",
    "整个项目",
    "工作区",
}
SEMANTIC_ALIASES = {
    "报表": ["report", "format", "line", "summary"],
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
    "上下文": ["context", "memory", "history"],
    "记忆": ["memory", "history", "preference"],
}


@dataclass
class SemanticMatch:
    relative_path: str
    score: float
    reason: str
    keywords: list[str] = field(default_factory=list)
    embedding_score: float = 0.0
    retrieval_score: float = 0.0


@dataclass
class WorkspaceSemanticResult:
    query_terms: list[str] = field(default_factory=list)
    matches: list[SemanticMatch] = field(default_factory=list)
    embedding_provider: str = "hashing"
    embedding_model: str = ""
    fallback_used: bool = False
    warning: str = ""

    def to_prompt_text(self) -> str:
        """
        将语义检索结果整理为可放入提示词的文本。
        """

        if not self.matches:
            return "(semantic retrieval unavailable)"

        lines = [
            f"- Embedding provider: {self.embedding_provider}",
            f"- Embedding model: {self.embedding_model or '(not configured)'}",
            "- Method: bge-m3 embedding similarity + workspace retrieval signals.",
        ]
        if self.fallback_used and self.warning:
            lines.append(f"- Embedding fallback: {self.warning}")

        if self.query_terms:
            lines.append("- Query concepts:")
            lines.append(f"  - {', '.join(self.query_terms[:8])}")

        lines.append("- Semantic retrieval highlights:")
        for match in self.matches:
            lines.append(
                f"  - {match.relative_path} "
                f"(score={match.score:.3f}, embedding={match.embedding_score:.3f}, "
                f"retrieval={match.retrieval_score:.3f}): {match.reason}"
            )

        return "\n".join(lines)

    def to_user_summary(self) -> str:
        """
        生成适合直接展示给用户的简短摘要。
        """

        if not self.matches:
            return ""

        files = "、".join(match.relative_path for match in self.matches[:3])
        provider = self.embedding_model or self.embedding_provider
        return f"Embedding 语义检索（{provider}）优先命中的文件：{files}"


class WorkspaceSemanticTool:
    """
    基于 bge-m3 等 embedding 模型对候选文件做语义相关性排序。
    """

    def __init__(self) -> None:
        self.embedding_provider = build_embedding_provider_from_env()

    def rank(
        self,
        context: AgentContextModel,
        prompt: str,
        search_result: WorkspaceSearchResult,
    ) -> WorkspaceSemanticResult:
        if not search_result.candidate_files:
            return WorkspaceSemanticResult()

        query_text = self._build_query_text(context, prompt)
        query_tokens = self._tokenize(query_text)
        if not query_text.strip():
            return WorkspaceSemanticResult()

        document_texts = [
            self._build_document_text(snapshot)
            for snapshot in search_result.candidate_files
        ]
        embedding_result = self.embedding_provider.embed_texts([query_text] + document_texts)
        matrix = normalize_matrix(embedding_result.vectors)
        if matrix.ndim != 2 or matrix.shape[0] != len(document_texts) + 1:
            return WorkspaceSemanticResult(
                query_terms=self._summarize_query_terms(query_tokens),
                embedding_provider=embedding_result.provider_name,
                embedding_model=embedding_result.model_name,
                fallback_used=True,
                warning="Embedding output shape is invalid.",
            )

        query_vector = matrix[0]
        document_vectors = matrix[1:]
        embedding_scores = self._embedding_scores(query_vector, document_vectors)
        documentation_requested = mentions_documentation(prompt)

        matches: list[SemanticMatch] = []
        for index, snapshot in enumerate(search_result.candidate_files):
            document_tokens = self._tokenize(document_texts[index])
            keywords = self._top_keywords(query_tokens, document_tokens)
            retrieval_score = self._normalize_retrieval_score(snapshot)
            keyword_score = self._keyword_overlap_score(query_tokens, document_tokens)
            domain_score = self._domain_hint_score(prompt, snapshot, document_texts[index])
            embedding_score = float(embedding_scores[index])

            score = (
                0.74 * embedding_score
                + 0.08 * retrieval_score
                + 0.08 * keyword_score
                + 0.10 * domain_score
            )
            if not documentation_requested and snapshot.relative_path.lower().endswith(".md"):
                score *= 0.72
            if score <= 0:
                continue

            reason = self._build_reason(
                snapshot.reason,
                keywords,
                embedding_score,
                keyword_score,
                domain_score,
            )
            matches.append(
                SemanticMatch(
                    relative_path=snapshot.relative_path,
                    score=score,
                    reason=reason,
                    keywords=keywords,
                    embedding_score=embedding_score,
                    retrieval_score=retrieval_score,
                )
            )

        matches.sort(key=lambda item: item.score, reverse=True)
        return WorkspaceSemanticResult(
            query_terms=self._summarize_query_terms(query_tokens),
            matches=matches[:4],
            embedding_provider=embedding_result.provider_name,
            embedding_model=embedding_result.model_name,
            fallback_used=embedding_result.fallback_used,
            warning=embedding_result.warning,
        )

    def _build_query_text(self, context: AgentContextModel, prompt: str) -> str:
        parts = [prompt]
        if context.selectedText:
            parts.append(context.selectedText)
        return "\n".join(part for part in parts if part)

    def _build_document_text(self, snapshot: WorkspaceFileSnapshot) -> str:
        content = snapshot.full_content.strip()
        if len(content) > 4500:
            content = content[:4500] + "\n...[truncated by semantic embedding]"

        return "\n".join(
            [
                f"Path: {snapshot.relative_path}",
                f"Retrieval reason: {snapshot.reason}",
                content or snapshot.excerpt,
            ]
        )

    def _embedding_scores(
        self,
        query_vector: np.ndarray,
        document_vectors: np.ndarray,
    ) -> np.ndarray:
        if document_vectors.size == 0:
            return np.asarray([], dtype=np.float64)

        raw_scores = document_vectors @ query_vector
        return np.clip((raw_scores + 1.0) / 2.0, 0.0, 1.0)

    def _normalize_retrieval_score(self, snapshot: WorkspaceFileSnapshot) -> float:
        return min(max(float(snapshot.score), 0.0) / 120.0, 1.0)

    def _keyword_overlap_score(self, query_tokens: list[str], document_tokens: list[str]) -> float:
        if not query_tokens or not document_tokens:
            return 0.0

        query_terms = set(query_tokens)
        document_terms = set(document_tokens)
        if not query_terms:
            return 0.0

        shared_ratio = len(query_terms & document_terms) / len(query_terms)
        return min(shared_ratio, 1.0)

    def _domain_hint_score(
        self,
        prompt: str,
        snapshot: WorkspaceFileSnapshot,
        document_text: str,
    ) -> float:
        prompt_lower = prompt.lower()
        target_text = f"{snapshot.relative_path} {snapshot.reason}".lower()
        content_text = document_text.lower()
        score = 0.0

        for source_word, aliases in SEMANTIC_ALIASES.items():
            if source_word not in prompt_lower:
                continue

            if any(alias in target_text for alias in aliases):
                score = max(score, 1.0)
            elif any(alias in content_text for alias in aliases):
                score = max(score, 0.45)

        for token in ASCII_TOKEN_PATTERN.findall(prompt_lower):
            if token in target_text:
                score = max(score, 0.72)

        return score

    def _tokenize(self, text: str) -> list[str]:
        normalized = text.lower()
        tokens: list[str] = []

        for token in ASCII_TOKEN_PATTERN.findall(normalized):
            tokens.extend(self._expand_ascii_token(token))

        for segment in CJK_TOKEN_PATTERN.findall(normalized):
            tokens.append(segment)
            tokens.extend(self._build_cjk_ngrams(segment))

        expanded = list(tokens)
        for token in tokens:
            expanded.extend(self._expand_semantic_aliases(token))

        return [
            token
            for token in expanded
            if len(token) >= 2 and token not in STOPWORDS
        ]

    def _expand_ascii_token(self, token: str) -> list[str]:
        expanded = {token}
        for piece in re.split(r"[./_-]+", token):
            if len(piece) >= 2:
                expanded.add(piece)
        return sorted(expanded)

    def _build_cjk_ngrams(self, segment: str) -> list[str]:
        if len(segment) <= 2:
            return [segment]

        grams: list[str] = []
        for size in (2, 3):
            if len(segment) < size:
                continue
            for index in range(0, len(segment) - size + 1):
                grams.append(segment[index : index + size])
        return grams

    def _expand_semantic_aliases(self, token: str) -> list[str]:
        expanded: list[str] = []
        for source, aliases in SEMANTIC_ALIASES.items():
            if source in token:
                expanded.extend(aliases)
        return expanded

    def _top_keywords(self, query_tokens: list[str], document_tokens: list[str]) -> list[str]:
        if not query_tokens or not document_tokens:
            return []

        query_counts = Counter(query_tokens)
        document_counts = Counter(document_tokens)
        shared = [
            (term, query_counts[term] * document_counts[term])
            for term in set(query_counts) & set(document_counts)
        ]
        shared.sort(key=lambda item: item[1], reverse=True)
        return [term for term, _ in shared[:3]]

    def _build_reason(
        self,
        fallback_reason: str,
        keywords: list[str],
        embedding_score: float,
        keyword_score: float,
        domain_score: float,
    ) -> str:
        details = [f"embedding 相似度 {embedding_score:.3f}"]
        if keywords:
            details.append(f"关键词：{'、'.join(keywords)}")
        if keyword_score > 0:
            details.append(f"词面重合 {keyword_score:.3f}")
        if domain_score > 0:
            details.append(f"领域提示 {domain_score:.3f}")

        return f"{'；'.join(details)}；{fallback_reason}"

    def _summarize_query_terms(self, query_tokens: list[str]) -> list[str]:
        counts = Counter(query_tokens)
        ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        return [term for term, _ in ranked[:8]]
