from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal

import numpy as np

from backend.ml.context_candidate import build_workspace_context_chunks
from backend.ml.embedding_provider import EmbeddingResult, build_embedding_provider_from_env, normalize_matrix
from backend.models import AgentContextModel, ConversationTurnModel
from backend.request_classifier import mentions_documentation
from backend.tools.workspace_search_tool import WorkspaceSearchResult
from backend.tools.workspace_semantic_tool import WorkspaceSemanticResult


CandidateSource = Literal["conversation", "workspace", "memory"]

DOMAIN_FILE_HINTS = {
    "报表": ["report"],
    "报告": ["report"],
    "平均分": ["report", "models", "manager"],
    "成绩": ["student", "score", "models", "manager", "report"],
    "学生": ["student", "models", "manager"],
    "数据": ["storage", "data", "json"],
    "加载": ["storage", "load"],
    "读取": ["storage", "read"],
    "保存": ["storage", "save"],
    "存储": ["storage"],
    "模型": ["models", "model"],
    "对象": ["models", "model"],
    "管理": ["manager"],
    "封装": ["manager", "storage", "helper"],
    "重构": ["manager", "storage", "report", "models"],
    "入口": ["main"],
    "主程序": ["main"],
    "文档": ["readme", "docs"],
    "说明": ["readme", "docs"],
}


@dataclass
class AttentionContextCandidate:
    source: CandidateSource
    identifier: str
    title: str
    content: str
    retrieval_score: float = 0.0
    chunk_type: str = ""
    location: str = ""


@dataclass
class AttentionContextMatch:
    source: CandidateSource
    identifier: str
    title: str
    weight: float
    attention_weight: float
    cosine_similarity: float
    retrieval_score: float
    head_weights: list[float] = field(default_factory=list)
    chunk_type: str = ""
    location: str = ""
    excerpt: str = ""


@dataclass
class AttentionMemoryResult:
    matches: list[AttentionContextMatch] = field(default_factory=list)
    head_count: int = 4
    embedding_provider: str = "hashing"
    embedding_model: str = ""
    fallback_used: bool = False
    warning: str = ""

    def to_prompt_text(self) -> str:
        if not self.matches:
            return "(attention memory unavailable)"

        lines = [
            "Attention-selected context:",
            f"- Embedding provider: {self.embedding_provider}",
            f"- Embedding model: {self.embedding_model or '(not configured)'}",
            f"- Method: embedding similarity + temperature-calibrated multi-head attention reranking ({self.head_count} heads).",
            "- Role: rank candidate history, memory, project snippets, and derived call-chain snippets before calling the LLM.",
        ]
        if self.fallback_used and self.warning:
            lines.append(f"- Embedding fallback: {self.warning}")

        for match in self.matches:
            heads = ", ".join(f"{value:.3f}" for value in match.head_weights)
            lines.append(
                f"<attention_context source=\"{match.source}\" id=\"{match.identifier}\" "
                f"chunk_type=\"{match.chunk_type}\" location=\"{match.location}\" "
                f"weight=\"{match.weight:.3f}\" attention=\"{match.attention_weight:.3f}\" "
                f"cosine=\"{match.cosine_similarity:.3f}\" retrieval=\"{match.retrieval_score:.3f}\" "
                f"heads=\"{heads}\">\n"
                f"Title: {match.title}\n"
                f"{match.excerpt}\n"
                "</attention_context>"
            )
        return "\n".join(lines)

    def to_user_summary(self) -> str:
        if not self.matches:
            return ""

        labels = "、".join(match.title for match in self.matches[:3])
        return f"注意力上下文模块优先选择：{labels}"


class AttentionMemoryTool:
    """
    基于 Embedding 与多头注意力的上下文选择器。
    """

    def __init__(self, head_count: int = 4, top_k: int = 8, enable_call_chain: bool = True) -> None:
        self.head_count = head_count
        self.top_k = top_k
        self.enable_call_chain = enable_call_chain
        self.max_context_chars = 6000
        self.attention_temperature = 0.08
        self.embedding_provider = build_embedding_provider_from_env()

    def select(
        self,
        context: AgentContextModel,
        prompt: str,
        search_result: WorkspaceSearchResult | None = None,
        semantic_result: WorkspaceSemanticResult | None = None,
        conversation_history: list[ConversationTurnModel] | None = None,
        memory_items: list[str] | None = None,
    ) -> AttentionMemoryResult:
        candidates = self._build_candidates(
            context,
            search_result,
            semantic_result,
            conversation_history or [],
            memory_items or [],
        )
        if not candidates:
            return AttentionMemoryResult(head_count=self.head_count)

        query_text = self._build_query_text(context, prompt)
        embedding_result = self.embedding_provider.embed_texts(
            [query_text] + [candidate.content for candidate in candidates]
        )
        matrix = self._prepare_attention_matrix(embedding_result)
        query_vector = matrix[0]
        candidate_vectors = matrix[1:]

        head_weights = self._multi_head_attention_weights(query_vector, candidate_vectors)
        attention_scores = np.mean(np.vstack(head_weights), axis=0)
        attention_rank_scores = self._normalize_scores(attention_scores)
        cosine_scores = self._cosine_scores(query_vector, candidate_vectors)
        retrieval_scores = self._normalize_retrieval_scores(candidates)
        domain_scores = self._domain_hint_scores(prompt, candidates)

        documentation_requested = mentions_documentation(prompt)
        code_location_request = self._is_code_location_request(prompt)
        matches: list[AttentionContextMatch] = []
        for index, candidate in enumerate(candidates):
            final_weight = (
                0.48 * float(attention_rank_scores[index])
                + 0.25 * float(cosine_scores[index])
                + 0.15 * float(retrieval_scores[index])
                + 0.12 * float(domain_scores[index])
            )
            if (
                candidate.source == "workspace"
                and candidate.identifier.lower().endswith(".md")
                and not documentation_requested
            ):
                final_weight *= 0.72
            if candidate.chunk_type.startswith("call_chain_"):
                final_weight += 0.08
                if candidate.chunk_type == "call_chain_method":
                    final_weight += 0.14
                if float(domain_scores[index]) > 0:
                    final_weight += 0.06
            if code_location_request and candidate.source == "memory":
                final_weight *= 0.86
            if code_location_request and candidate.source == "workspace":
                final_weight += 0.04
            final_weight = min(final_weight, 1.0)

            matches.append(
                AttentionContextMatch(
                    source=candidate.source,
                    identifier=candidate.identifier,
                    title=candidate.title,
                    weight=final_weight,
                    attention_weight=float(attention_scores[index]),
                    cosine_similarity=float(cosine_scores[index]),
                    retrieval_score=float(retrieval_scores[index]),
                    head_weights=[float(weights[index]) for weights in head_weights],
                    chunk_type=candidate.chunk_type,
                    location=candidate.location,
                    excerpt=self._truncate(candidate.content, 900),
                )
            )

        matches.sort(key=lambda item: item.weight, reverse=True)
        matches = self._apply_source_aware_rerank(matches, code_location_request)
        selected_matches = self._select_top_matches(matches)
        return AttentionMemoryResult(
            matches=selected_matches,
            head_count=self.head_count,
            embedding_provider=embedding_result.provider_name,
            embedding_model=embedding_result.model_name,
            fallback_used=embedding_result.fallback_used,
            warning=embedding_result.warning,
        )

    def _build_candidates(
        self,
        context: AgentContextModel,
        search_result: WorkspaceSearchResult | None,
        semantic_result: WorkspaceSemanticResult | None,
        conversation_history: list[ConversationTurnModel],
        memory_items: list[str],
    ) -> list[AttentionContextCandidate]:
        candidates: list[AttentionContextCandidate] = []

        for index, turn in enumerate(conversation_history[-10:], start=1):
            candidates.append(
                AttentionContextCandidate(
                    source="conversation",
                    identifier=f"turn-{index}",
                    title=f"最近对话 {index}（{turn.role}）",
                    content=f"{turn.role}: {turn.content}",
                    retrieval_score=0.35,
                    chunk_type="conversation_turn",
                )
            )

        if context.systemPrompt.strip():
            candidates.append(
                AttentionContextCandidate(
                    source="memory",
                    identifier="system-instruction",
                    title="系统提示记忆",
                    content=context.systemPrompt.strip(),
                    retrieval_score=0.5,
                    chunk_type="system_prompt",
                )
            )

        for index, item in enumerate(memory_items, start=1):
            if item.strip():
                candidates.append(
                    AttentionContextCandidate(
                        source="memory",
                        identifier=f"memory-{index}",
                        title=f"长期记忆 {index}",
                        content=item.strip(),
                        retrieval_score=0.55,
                        chunk_type="long_term_memory",
                    )
                )

        candidates.extend(self._infer_preference_memories(conversation_history))
        candidates.extend(self._build_workspace_candidates(search_result, semantic_result))
        return self._deduplicate_candidates(candidates)

    def _build_workspace_candidates(
        self,
        search_result: WorkspaceSearchResult | None,
        semantic_result: WorkspaceSemanticResult | None,
    ) -> list[AttentionContextCandidate]:
        if not search_result:
            return []

        candidates: list[AttentionContextCandidate] = []
        for chunk in build_workspace_context_chunks(
            search_result,
            semantic_result,
            enable_call_chain=self.enable_call_chain,
        ):
            candidates.append(
                AttentionContextCandidate(
                    source="workspace",
                    identifier=chunk.identifier,
                    title=chunk.title,
                    content=chunk.content,
                    retrieval_score=chunk.retrieval_score,
                    chunk_type=chunk.chunk_type,
                    location=chunk.location,
                )
            )

        return candidates

    def _infer_preference_memories(
        self,
        conversation_history: list[ConversationTurnModel],
    ) -> list[AttentionContextCandidate]:
        combined_user_text = "\n".join(
            turn.content for turn in conversation_history if turn.role == "user"
        )
        memories: list[AttentionContextCandidate] = []

        if any(keyword in combined_user_text for keyword in ["注释", "文档", "小白", "初学者"]):
            memories.append(
                AttentionContextCandidate(
                    source="memory",
                    identifier="comment-style-preference",
                    title="中文注释风格偏好",
                    content=(
                        "用户偏好：中文注释应正式、简洁、面向工程维护；"
                        "函数用途说明应尽量放在函数定义附近，避免在函数内部重复解释函数本身。"
                    ),
                    retrieval_score=0.62,
                    chunk_type="inferred_preference",
                )
            )

        if any(keyword in combined_user_text for keyword in ["多文件", "整个项目", "工程", "项目"]):
            memories.append(
                AttentionContextCandidate(
                    source="memory",
                    identifier="workspace-scope-preference",
                    title="项目级修改偏好",
                    content=(
                        "用户偏好：涉及项目优化时，应优先检索整个工作区，"
                        "再规划多文件修改方案，而不是只处理当前活动文件。"
                    ),
                    retrieval_score=0.66,
                    chunk_type="inferred_preference",
                )
            )

        if any(keyword in combined_user_text for keyword in ["diff", "预览", "确认", "红绿"]):
            memories.append(
                AttentionContextCandidate(
                    source="memory",
                    identifier="diff-confirmation-preference",
                    title="Diff 确认偏好",
                    content="用户偏好：文件修改需要先显示红绿 diff 预览，再由用户确认后写回。",
                    retrieval_score=0.64,
                    chunk_type="inferred_preference",
                )
            )

        return memories

    def _build_query_text(self, context: AgentContextModel, prompt: str) -> str:
        parts = [prompt]
        if context.selectedText:
            parts.append(context.selectedText)
        if context.activeFile:
            parts.append(context.activeFile)
        return "\n".join(part for part in parts if part)

    def _prepare_attention_matrix(self, embedding_result: EmbeddingResult) -> np.ndarray:
        matrix = normalize_matrix(embedding_result.vectors)
        if matrix.ndim != 2 or matrix.shape[0] == 0:
            return np.zeros((0, self.head_count), dtype=np.float64)

        current_size = matrix.shape[1]
        remainder = current_size % self.head_count
        if remainder == 0:
            return matrix

        target_size = current_size + (self.head_count - remainder)
        padded = np.zeros((matrix.shape[0], target_size), dtype=np.float64)
        padded[:, :current_size] = matrix
        return padded

    def _multi_head_attention_weights(
        self,
        query_vector: np.ndarray,
        candidate_vectors: np.ndarray,
    ) -> list[np.ndarray]:
        if candidate_vectors.size == 0:
            return []

        vector_size = query_vector.shape[0]
        head_size = max(1, vector_size // self.head_count)
        weights: list[np.ndarray] = []

        for head_index in range(self.head_count):
            start = head_index * head_size
            end = vector_size if head_index == self.head_count - 1 else start + head_size
            query = self._normalize_vector(query_vector[start:end])
            keys = normalize_matrix(candidate_vectors[:, start:end])
            scores = keys @ query / self.attention_temperature
            weights.append(self._softmax(scores))

        return weights

    def _cosine_scores(self, query_vector: np.ndarray, candidate_vectors: np.ndarray) -> np.ndarray:
        if candidate_vectors.size == 0:
            return np.asarray([], dtype=np.float64)

        scores = candidate_vectors @ query_vector
        return np.clip((scores + 1.0) / 2.0, 0.0, 1.0)

    def _normalize_retrieval_scores(self, candidates: list[AttentionContextCandidate]) -> np.ndarray:
        raw_scores = np.asarray([candidate.retrieval_score for candidate in candidates], dtype=np.float64)
        return self._normalize_scores(raw_scores)

    def _normalize_scores(self, raw_scores: np.ndarray) -> np.ndarray:
        if raw_scores.size == 0:
            return raw_scores

        min_score = float(raw_scores.min())
        max_score = float(raw_scores.max())
        if math.isclose(max_score, min_score):
            return np.full_like(raw_scores, 0.5)
        return (raw_scores - min_score) / (max_score - min_score)

    def _domain_hint_scores(
        self,
        prompt: str,
        candidates: list[AttentionContextCandidate],
    ) -> np.ndarray:
        normalized_prompt = prompt.lower()
        scores: list[float] = []

        for candidate in candidates:
            target_text = f"{candidate.identifier} {candidate.title}".lower()
            content_text = candidate.content.lower()
            score = 0.0

            for source_word, file_hints in DOMAIN_FILE_HINTS.items():
                if source_word not in normalized_prompt:
                    continue

                if any(hint in target_text for hint in file_hints):
                    score = max(score, 1.0)
                elif any(hint in content_text for hint in file_hints):
                    score = max(score, 0.45)

            for token in self._ascii_query_tokens(normalized_prompt):
                if token in target_text:
                    score = max(score, 0.72)

            scores.append(score)

        return np.asarray(scores, dtype=np.float64)

    def _ascii_query_tokens(self, prompt: str) -> list[str]:
        tokens: list[str] = []
        current = []
        for char in prompt:
            if char.isascii() and (char.isalnum() or char in {"_", "-", "."}):
                current.append(char)
                continue
            if len(current) >= 2:
                tokens.append("".join(current))
            current = []

        if len(current) >= 2:
            tokens.append("".join(current))

        return tokens

    def _deduplicate_candidates(
        self,
        candidates: list[AttentionContextCandidate],
    ) -> list[AttentionContextCandidate]:
        deduplicated: list[AttentionContextCandidate] = []
        seen: set[tuple[str, str, str]] = set()

        for candidate in candidates:
            key = (candidate.source, candidate.identifier.lower(), candidate.location.lower())
            if key in seen or not candidate.content.strip():
                continue
            seen.add(key)
            deduplicated.append(candidate)
        return deduplicated

    def _select_top_matches(self, matches: list[AttentionContextMatch]) -> list[AttentionContextMatch]:
        selected: list[AttentionContextMatch] = []
        used_chars = 0

        for match in matches:
            if len(selected) >= self.top_k:
                break
            next_size = len(match.excerpt)
            if selected and used_chars + next_size > self.max_context_chars:
                continue
            selected.append(match)
            used_chars += next_size

        return selected

    def _apply_source_aware_rerank(
        self,
        matches: list[AttentionContextMatch],
        code_location_request: bool,
    ) -> list[AttentionContextMatch]:
        if not code_location_request or not matches:
            return matches

        top_workspace_index = next(
            (index for index, match in enumerate(matches) if match.source == "workspace"),
            None,
        )
        if top_workspace_index is None or top_workspace_index == 0:
            return matches

        top_match = matches[0]
        workspace_match = matches[top_workspace_index]
        if top_match.source == "memory" and workspace_match.weight >= top_match.weight * 0.82:
            reordered = [workspace_match]
            reordered.extend(match for index, match in enumerate(matches) if index != top_workspace_index)
            return reordered

        return matches

    def _is_code_location_request(self, prompt: str) -> bool:
        normalized = prompt.lower()
        code_keywords = [
            "在哪里",
            "哪",
            "位置",
            "入口",
            "方法",
            "函数",
            "逻辑",
            "实现",
            "读取",
            "保存",
            "转换",
            "序列化",
            "校验",
            "计算",
            "生成",
            "代码",
            "文件",
            "class",
            "function",
            "method",
            "where",
            "implementation",
        ]
        return any(keyword in normalized for keyword in code_keywords)

    def _softmax(self, scores: np.ndarray) -> np.ndarray:
        if scores.size == 0:
            return scores

        stable = scores - np.max(scores)
        exp_scores = np.exp(stable)
        denominator = np.sum(exp_scores)
        if denominator <= 0:
            return np.zeros_like(scores)
        return exp_scores / denominator

    def _normalize_vector(self, vector: np.ndarray) -> np.ndarray:
        norm = float(np.linalg.norm(vector))
        if norm <= 0:
            return vector
        return vector / norm

    def _truncate(self, content: str, max_chars: int) -> str:
        cleaned = content.strip()
        if len(cleaned) <= max_chars:
            return cleaned
        return cleaned[:max_chars] + "\n...[truncated]"


def run_demo() -> AttentionMemoryResult:
    context = AgentContextModel(workspaceRoot="demo", activeFile="main.py")
    candidates = WorkspaceSearchResult()
    tool = AttentionMemoryTool()
    return tool.select(
        context=context,
        prompt="报表生成逻辑在哪里？",
        search_result=candidates,
        memory_items=[
            "report.py 负责格式化学生成绩报告。",
            "storage.py 负责读取和保存 JSON 数据。",
            "manager.py 负责协调学生数据管理流程。",
        ],
    )


if __name__ == "__main__":
    print(run_demo().to_prompt_text())
