import math
import re
from collections import Counter
from dataclasses import dataclass, field

from backend.models import AgentContextModel
from backend.request_classifier import mentions_documentation
from backend.tools.workspace_search_tool import WorkspaceSearchResult

# 文件说明：
# 本文件提供一个轻量级的项目语义检索模块。
# 当前实现不依赖额外深度学习推理服务，而是使用无监督的文本表示与相似度计算，
# 在本地对候选文件做相关性排序，适合毕设演示与后续替换为 embedding 模型。

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
}


@dataclass
class SemanticMatch:
    relative_path: str
    score: float
    reason: str
    keywords: list[str] = field(default_factory=list)


@dataclass
class WorkspaceSemanticResult:
    query_terms: list[str] = field(default_factory=list)
    matches: list[SemanticMatch] = field(default_factory=list)

    """
    将语义检索结果整理为可放入提示词的文本。
    """
    def to_prompt_text(self) -> str:
        if not self.matches:
            return "(semantic retrieval unavailable)"

        lines = []
        if self.query_terms:
            lines.append("- Query concepts:")
            lines.append(f"  - {', '.join(self.query_terms[:8])}")

        lines.append("- Semantic retrieval highlights:")
        for match in self.matches:
            lines.append(
                f"  - {match.relative_path} (score={match.score:.3f}): {match.reason}"
            )

        return "\n".join(lines)

    """
    生成适合直接展示给用户的简短摘要。
    """
    def to_user_summary(self) -> str:
        if not self.matches:
            return ""

        files = "、".join(match.relative_path for match in self.matches[:3])
        return f"语义检索优先命中的文件：{files}"


class WorkspaceSemanticTool:
    """
    基于无监督统计文本表示对候选文件做语义相关性排序。
    """

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
        if not query_tokens:
            return WorkspaceSemanticResult()

        document_tokens: dict[str, list[str]] = {}
        document_frequency: Counter[str] = Counter()

        for snapshot in search_result.candidate_files:
            combined_text = "\n".join(
                filter(
                    None,
                    [
                        snapshot.relative_path,
                        snapshot.reason,
                        snapshot.excerpt,
                    ],
                )
            )
            tokens = self._tokenize(combined_text)
            document_tokens[snapshot.relative_path] = tokens
            document_frequency.update(set(tokens))

        query_weights = self._build_tfidf_weights(
            query_tokens,
            document_frequency,
            len(document_tokens),
        )
        if not query_weights:
            return WorkspaceSemanticResult()

        documentation_requested = mentions_documentation(prompt)
        matches: list[SemanticMatch] = []
        for snapshot in search_result.candidate_files:
            tokens = document_tokens.get(snapshot.relative_path, [])
            if not tokens:
                continue

            document_weights = self._build_tfidf_weights(
                tokens,
                document_frequency,
                len(document_tokens),
            )
            score = self._cosine_similarity(query_weights, document_weights)
            if not documentation_requested and snapshot.relative_path.lower().endswith(".md"):
                score *= 0.72
            if score <= 0:
                continue

            keywords = self._top_keywords(query_weights, document_weights)
            reason = self._build_reason(snapshot.reason, keywords)
            matches.append(
                SemanticMatch(
                    relative_path=snapshot.relative_path,
                    score=score,
                    reason=reason,
                    keywords=keywords,
                )
            )

        matches.sort(key=lambda item: item.score, reverse=True)
        return WorkspaceSemanticResult(
            query_terms=self._summarize_query_terms(query_weights),
            matches=matches[:4],
        )

    def _build_query_text(self, context: AgentContextModel, prompt: str) -> str:
        parts = [prompt]
        if context.selectedText:
            parts.append(context.selectedText)
        return "\n".join(part for part in parts if part)

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

    def _build_tfidf_weights(
        self,
        tokens: list[str],
        document_frequency: Counter[str],
        document_count: int,
    ) -> dict[str, float]:
        counts = Counter(tokens)
        total = sum(counts.values())
        if total <= 0:
            return {}

        weights: dict[str, float] = {}
        for token, count in counts.items():
            tf = count / total
            idf = math.log((document_count + 1) / (document_frequency[token] + 1)) + 1.0
            weights[token] = tf * idf
        return weights

    def _cosine_similarity(
        self,
        left: dict[str, float],
        right: dict[str, float],
    ) -> float:
        common_terms = set(left) & set(right)
        if not common_terms:
            return 0.0

        numerator = sum(left[term] * right[term] for term in common_terms)
        left_norm = math.sqrt(sum(value * value for value in left.values()))
        right_norm = math.sqrt(sum(value * value for value in right.values()))
        if left_norm == 0 or right_norm == 0:
            return 0.0

        return numerator / (left_norm * right_norm)

    def _top_keywords(
        self,
        query_weights: dict[str, float],
        document_weights: dict[str, float],
    ) -> list[str]:
        shared = [
            (term, query_weights[term] * document_weights[term])
            for term in set(query_weights) & set(document_weights)
        ]
        shared.sort(key=lambda item: item[1], reverse=True)
        return [term for term, _ in shared[:3]]

    def _build_reason(self, fallback_reason: str, keywords: list[str]) -> str:
        if keywords:
            return f"语义命中关键词：{'、'.join(keywords)}；{fallback_reason}"
        return f"语义相关度较高；{fallback_reason}"

    def _summarize_query_terms(self, query_weights: dict[str, float]) -> list[str]:
        ranked = sorted(query_weights.items(), key=lambda item: item[1], reverse=True)
        return [term for term, _ in ranked[:8]]
