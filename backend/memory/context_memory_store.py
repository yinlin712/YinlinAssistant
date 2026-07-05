from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from backend.models import AgentContextModel, ContextSelectionModel, ConversationTurnModel, GenerateResponse


TOKEN_PATTERN = re.compile(r"[a-zA-Z_][a-zA-Z0-9_./-]{1,}|[\u4e00-\u9fff]{2,}")


@dataclass
class MemoryItem:
    title: str
    content: str
    source: str
    score: float = 0.0

    def to_attention_text(self) -> str:
        return f"{self.title}\n来源：{self.source}\n{self.content}"


class ContextMemoryStore:
    """
    使用 SQLite 保存历史对话、长期偏好和上下文选择诊断。
    """

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or resolve_memory_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def retrieve_memory_items(
        self,
        context: AgentContextModel,
        prompt: str,
        conversation_history: list[ConversationTurnModel] | None = None,
        limit: int = 8,
    ) -> list[str]:
        """
        检索适合送入 attention 候选池的跨会话记忆。
        """

        try:
            items = self._retrieve_memory_items(context, prompt, conversation_history or [], limit)
        except sqlite3.Error:
            return []

        return [item.to_attention_text() for item in items[:limit]]

    def remember_response(
        self,
        request_prompt: str,
        context: AgentContextModel,
        response: GenerateResponse,
    ) -> None:
        """
        将本次请求、回答摘要、上下文选择结果和可推断偏好写入 SQLite。
        """

        try:
            self._remember_response(request_prompt, context, response)
        except sqlite3.Error:
            return

    def inspect_memory(self, workspace_root: str = "", limit: int = 20) -> dict[str, object]:
        """
        返回记忆库概览，供调试接口和后续前端工具面板使用。
        """

        safe_limit = min(max(limit, 1), 100)
        workspace_key = ""
        normalized_workspace_root = ""
        where_clause = ""
        params: tuple[object, ...] = ()

        if workspace_root.strip():
            workspace_key, normalized_workspace_root = workspace_identity(
                AgentContextModel(workspaceRoot=workspace_root.strip())
            )
            where_clause = "WHERE workspace_key = ?"
            params = (workspace_key,)

        with self._connect() as conn:
            counts = {
                "conversationMessages": self._count_rows(conn, "conversation_messages", where_clause, params),
                "longTermMemories": self._count_rows(conn, "long_term_memories", where_clause, params),
                "contextSelectionEvents": self._count_rows(conn, "context_selection_events", where_clause, params),
            }
            recent_messages = [
                {
                    "id": row["id"],
                    "workspaceRoot": row["workspace_root"],
                    "role": row["role"],
                    "content": row["content"],
                    "activeFile": row["active_file"],
                    "createdAt": row["created_at"],
                }
                for row in conn.execute(
                    f"""
                    SELECT id, workspace_root, role, content, active_file, created_at
                    FROM conversation_messages
                    {where_clause}
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (*params, safe_limit),
                ).fetchall()
            ]
            long_term_memories = [
                {
                    "id": row["id"],
                    "workspaceRoot": row["workspace_root"],
                    "category": row["category"],
                    "title": row["title"],
                    "content": row["content"],
                    "weight": row["weight"],
                    "updatedAt": row["updated_at"],
                }
                for row in conn.execute(
                    f"""
                    SELECT id, workspace_root, category, title, content, weight, updated_at
                    FROM long_term_memories
                    {where_clause}
                    ORDER BY updated_at DESC
                    LIMIT ?
                    """,
                    (*params, safe_limit),
                ).fetchall()
            ]
            context_events = [
                {
                    "id": row["id"],
                    "workspaceRoot": row["workspace_root"],
                    "prompt": row["prompt"],
                    "summary": row["summary"],
                    "embeddingProvider": row["embedding_provider"],
                    "embeddingModel": row["embedding_model"],
                    "topMatches": parse_event_top_matches(row["matches_json"]),
                    "createdAt": row["created_at"],
                }
                for row in conn.execute(
                    f"""
                    SELECT id, workspace_root, prompt, summary, embedding_provider,
                           embedding_model, matches_json, created_at
                    FROM context_selection_events
                    {where_clause}
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (*params, safe_limit),
                ).fetchall()
            ]

        return {
            "databasePath": str(self.db_path),
            "workspaceRoot": normalized_workspace_root or "(all)",
            "workspaceKey": workspace_key or "(all)",
            "counts": counts,
            "recentMessages": recent_messages,
            "longTermMemories": long_term_memories,
            "contextSelectionEvents": context_events,
        }

    def clear_memory(self, workspace_root: str = "") -> dict[str, object]:
        """
        清空记忆库；传入 workspace_root 时只清理对应工作区。
        """

        workspace_key = ""
        normalized_workspace_root = ""
        where_clause = ""
        params: tuple[object, ...] = ()

        if workspace_root.strip():
            workspace_key, normalized_workspace_root = workspace_identity(
                AgentContextModel(workspaceRoot=workspace_root.strip())
            )
            where_clause = "WHERE workspace_key = ?"
            params = (workspace_key,)

        with self._connect() as conn:
            deleted_counts = {
                "conversationMessages": self._count_rows(conn, "conversation_messages", where_clause, params),
                "longTermMemories": self._count_rows(conn, "long_term_memories", where_clause, params),
                "contextSelectionEvents": self._count_rows(conn, "context_selection_events", where_clause, params),
            }
            conn.execute(f"DELETE FROM conversation_messages {where_clause}", params)
            conn.execute(f"DELETE FROM long_term_memories {where_clause}", params)
            conn.execute(f"DELETE FROM context_selection_events {where_clause}", params)

        return {
            "databasePath": str(self.db_path),
            "workspaceRoot": normalized_workspace_root or "(all)",
            "workspaceKey": workspace_key or "(all)",
            "deleted": deleted_counts,
        }

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS conversation_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    workspace_key TEXT NOT NULL,
                    workspace_root TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    active_file TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS long_term_memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    workspace_key TEXT NOT NULL,
                    workspace_root TEXT NOT NULL,
                    category TEXT NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    weight REAL NOT NULL DEFAULT 0.5,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(workspace_key, category, title)
                );

                CREATE TABLE IF NOT EXISTS context_selection_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    workspace_key TEXT NOT NULL,
                    workspace_root TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    response_excerpt TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    embedding_provider TEXT NOT NULL,
                    embedding_model TEXT NOT NULL,
                    matches_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_conversation_workspace_created
                ON conversation_messages(workspace_key, created_at);

                CREATE INDEX IF NOT EXISTS idx_memory_workspace_updated
                ON long_term_memories(workspace_key, updated_at);

                CREATE INDEX IF NOT EXISTS idx_context_selection_workspace_created
                ON context_selection_events(workspace_key, created_at);
                """
            )

    def _retrieve_memory_items(
        self,
        context: AgentContextModel,
        prompt: str,
        conversation_history: list[ConversationTurnModel],
        limit: int,
    ) -> list[MemoryItem]:
        workspace_key, _workspace_root = workspace_identity(context)
        query_tokens = set(tokenize_for_memory(prompt))
        live_history_text = "\n".join(turn.content for turn in conversation_history[-6:])
        if live_history_text:
            query_tokens.update(tokenize_for_memory(live_history_text))

        items: list[MemoryItem] = []
        with self._connect() as conn:
            memory_rows = conn.execute(
                """
                SELECT title, content, category, weight, updated_at
                FROM long_term_memories
                WHERE workspace_key = ?
                ORDER BY updated_at DESC
                LIMIT 24
                """,
                (workspace_key,),
            ).fetchall()
            for row in memory_rows:
                text = f"{row['title']}\n{row['content']}"
                items.append(
                    MemoryItem(
                        title=row["title"],
                        content=row["content"],
                        source=f"长期记忆/{row['category']}",
                        score=float(row["weight"]) + overlap_score(query_tokens, text),
                    )
                )

            event_rows = conn.execute(
                """
                SELECT prompt, summary, embedding_provider, embedding_model, matches_json, created_at
                FROM context_selection_events
                WHERE workspace_key = ?
                ORDER BY created_at DESC
                LIMIT 12
                """,
                (workspace_key,),
            ).fetchall()
            for row in event_rows:
                content = build_context_event_memory(row)
                items.append(
                    MemoryItem(
                        title="最近上下文选择结果",
                        content=content,
                        source="上下文选择日志",
                        score=0.45 + overlap_score(query_tokens, f"{row['prompt']}\n{content}"),
                    )
                )

            history_rows = conn.execute(
                """
                SELECT role, content, active_file, created_at
                FROM conversation_messages
                WHERE workspace_key = ?
                ORDER BY created_at DESC
                LIMIT 16
                """,
                (workspace_key,),
            ).fetchall()
            for row in history_rows:
                content = f"{row['role']}: {row['content']}"
                if row["active_file"]:
                    content = f"{content}\nActive file: {row['active_file']}"
                items.append(
                    MemoryItem(
                        title="历史对话片段",
                        content=content,
                        source="SQLite 历史对话",
                        score=0.32 + overlap_score(query_tokens, content),
                    )
                )

        items.sort(key=lambda item: item.score, reverse=True)
        return deduplicate_memory_items(items)[:limit]

    def _remember_response(
        self,
        request_prompt: str,
        context: AgentContextModel,
        response: GenerateResponse,
    ) -> None:
        workspace_key, workspace_root = workspace_identity(context)
        now = utc_now()
        response_excerpt = truncate_text(response.content, 1600)

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO conversation_messages
                (workspace_key, workspace_root, role, content, active_file, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    workspace_key,
                    workspace_root,
                    "user",
                    truncate_text(request_prompt, 2400),
                    context.activeFile or "",
                    now,
                ),
            )
            conn.execute(
                """
                INSERT INTO conversation_messages
                (workspace_key, workspace_root, role, content, active_file, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    workspace_key,
                    workspace_root,
                    "agent",
                    response_excerpt,
                    context.activeFile or "",
                    now,
                ),
            )

            self._upsert_inferred_memories(conn, workspace_key, workspace_root, request_prompt, response, now)
            if response.contextSelection.available:
                conn.execute(
                    """
                    INSERT INTO context_selection_events
                    (workspace_key, workspace_root, prompt, response_excerpt, summary,
                     embedding_provider, embedding_model, matches_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        workspace_key,
                        workspace_root,
                        truncate_text(request_prompt, 2400),
                        response_excerpt,
                        response.contextSelection.summary,
                        response.contextSelection.embeddingProvider,
                        response.contextSelection.embeddingModel,
                        json.dumps(
                            [match.model_dump() for match in response.contextSelection.matches[:6]],
                            ensure_ascii=False,
                        ),
                        now,
                    ),
                )
            self._prune_old_rows(conn, workspace_key)

    def _upsert_inferred_memories(
        self,
        conn: sqlite3.Connection,
        workspace_key: str,
        workspace_root: str,
        prompt: str,
        response: GenerateResponse,
        now: str,
    ) -> None:
        memories = infer_long_term_memories(prompt, response)
        for category, title, content, weight in memories:
            conn.execute(
                """
                INSERT INTO long_term_memories
                (workspace_key, workspace_root, category, title, content, weight, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(workspace_key, category, title) DO UPDATE SET
                    content = excluded.content,
                    weight = max(long_term_memories.weight, excluded.weight),
                    updated_at = excluded.updated_at
                """,
                (workspace_key, workspace_root, category, title, content, weight, now, now),
            )

    def _prune_old_rows(self, conn: sqlite3.Connection, workspace_key: str) -> None:
        conn.execute(
            """
            DELETE FROM conversation_messages
            WHERE workspace_key = ?
              AND id NOT IN (
                SELECT id FROM conversation_messages
                WHERE workspace_key = ?
                ORDER BY created_at DESC
                LIMIT 240
              )
            """,
            (workspace_key, workspace_key),
        )
        conn.execute(
            """
            DELETE FROM context_selection_events
            WHERE workspace_key = ?
              AND id NOT IN (
                SELECT id FROM context_selection_events
                WHERE workspace_key = ?
                ORDER BY created_at DESC
                LIMIT 80
              )
            """,
            (workspace_key, workspace_key),
        )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _count_rows(
        self,
        conn: sqlite3.Connection,
        table_name: str,
        where_clause: str,
        params: tuple[object, ...],
    ) -> int:
        row = conn.execute(
            f"SELECT COUNT(*) AS count FROM {table_name} {where_clause}",
            params,
        ).fetchone()
        return int(row["count"] if row else 0)


def resolve_memory_db_path() -> Path:
    raw_path = os.getenv("CODE_AGENT_MEMORY_DB", "").strip()
    if raw_path:
        return Path(raw_path).expanduser()
    return Path.cwd() / "data" / "code_agent_memory.sqlite3"


def workspace_identity(context: AgentContextModel) -> tuple[str, str]:
    workspace_root = normalize_workspace_root(context.workspaceRoot or "global")
    digest = hashlib.sha1(workspace_root.encode("utf-8", errors="ignore")).hexdigest()
    return digest, workspace_root


def normalize_workspace_root(workspace_root: str) -> str:
    if workspace_root == "global":
        return workspace_root
    try:
        return str(Path(workspace_root).resolve()).replace("\\", "/").lower()
    except OSError:
        return workspace_root.replace("\\", "/").lower()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def tokenize_for_memory(text: str) -> list[str]:
    return [token.lower() for token in TOKEN_PATTERN.findall(text or "") if len(token) >= 2]


def overlap_score(query_tokens: set[str], text: str) -> float:
    if not query_tokens:
        return 0.0
    target_tokens = set(tokenize_for_memory(text))
    if not target_tokens:
        return 0.0
    return min(len(query_tokens & target_tokens) / max(len(query_tokens), 1), 1.0)


def deduplicate_memory_items(items: list[MemoryItem]) -> list[MemoryItem]:
    deduplicated: list[MemoryItem] = []
    seen: set[str] = set()
    for item in items:
        key = hashlib.sha1(item.content.encode("utf-8", errors="ignore")).hexdigest()
        if key in seen or not item.content.strip():
            continue
        seen.add(key)
        deduplicated.append(item)
    return deduplicated


def build_context_event_memory(row: sqlite3.Row) -> str:
    matches = []
    try:
        raw_matches = json.loads(row["matches_json"])
        for match in raw_matches[:4]:
            title = str(match.get("title") or match.get("identifier") or "")
            weight = match.get("weight")
            if title:
                matches.append(f"{title}({float(weight):.3f})")
    except (TypeError, ValueError, json.JSONDecodeError):
        matches = []

    match_text = "、".join(matches) if matches else "无可用 Top 上下文"
    return (
        f"用户请求：{row['prompt']}\n"
        f"选择摘要：{row['summary']}\n"
        f"Embedding：{row['embedding_model'] or row['embedding_provider']}\n"
        f"Top 上下文：{match_text}"
    )


def parse_event_top_matches(matches_json: str) -> list[dict[str, object]]:
    try:
        raw_matches = json.loads(matches_json)
    except (TypeError, json.JSONDecodeError):
        return []

    parsed: list[dict[str, object]] = []
    for match in raw_matches[:6]:
        if not isinstance(match, dict):
            continue
        parsed.append(
            {
                "source": match.get("source", ""),
                "identifier": match.get("identifier", ""),
                "title": match.get("title", ""),
                "chunkType": match.get("chunkType", ""),
                "location": match.get("location", ""),
                "weight": match.get("weight", 0.0),
                "attentionWeight": match.get("attentionWeight", 0.0),
                "cosineSimilarity": match.get("cosineSimilarity", 0.0),
                "retrievalScore": match.get("retrievalScore", 0.0),
            }
        )
    return parsed


def infer_long_term_memories(
    prompt: str,
    response: GenerateResponse,
) -> list[tuple[str, str, str, float]]:
    normalized = prompt.lower()
    memories: list[tuple[str, str, str, float]] = []

    if any(keyword in normalized for keyword in ["注释", "文档", "小白", "初学者", "正式"]):
        memories.append(
            (
                "preference",
                "中文注释与说明偏好",
                "用户关注中文注释、文档说明或初学者可读性。后续回答应保持中文表达正式、简洁，代码注释只放在必要位置。",
                0.72,
            )
        )

    if any(keyword in normalized for keyword in ["多文件", "整个项目", "项目级", "工程级", "工作区", "codebase"]):
        memories.append(
            (
                "preference",
                "项目级上下文偏好",
                "用户提出项目级需求时，应优先检索整个工作区，结合多文件关系生成方案，而不是只处理当前活动文件。",
                0.76,
            )
        )

    if any(keyword in normalized for keyword in ["diff", "预览", "确认", "红绿", "写回"]):
        memories.append(
            (
                "preference",
                "Diff 预览与确认偏好",
                "用户希望文件修改先生成红绿 diff 预览，并在确认后再写回磁盘。",
                0.74,
            )
        )

    if response.actions:
        files = "、".join(Path(action.targetFile).name for action in response.actions[:6])
        memories.append(
            (
                "project",
                "最近修改文件集合",
                f"最近一次修改或规划涉及这些文件：{files}。用户请求为：{truncate_text(prompt, 240)}",
                0.62,
            )
        )

    if response.contextSelection.available and response.contextSelection.matches:
        top_titles = "、".join(match.title for match in response.contextSelection.matches[:4])
        memories.append(
            (
                "context-selection",
                "最近注意力上下文选择",
                f"最近一次上下文选择优先参考：{top_titles}。选择摘要：{response.contextSelection.summary}",
                0.58,
            )
        )

    return memories


def truncate_text(content: str, max_chars: int) -> str:
    cleaned = content.strip()
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[:max_chars] + "\n...[truncated]"
