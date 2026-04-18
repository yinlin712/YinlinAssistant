import re
from dataclasses import dataclass, field
from pathlib import Path

from backend.models import AgentContextModel
from backend.request_classifier import mentions_documentation

# 文件说明：
# 本文件负责在工作区范围内挑选与当前请求最相关的候选文件。
# 在弱模型条件下，稳定的候选文件集合比复杂提示词更重要，因此这里优先使用规则筛选。

TEXT_FILE_SUFFIXES = {
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".json",
    ".md",
    ".txt",
    ".yaml",
    ".yml",
    ".toml",
    ".css",
    ".html",
    ".sql",
    ".sh",
    ".ps1",
}

IGNORED_DIRECTORIES = {
    ".git",
    ".idea",
    ".next",
    ".vscode-test",
    "__pycache__",
    "dist",
    "node_modules",
    "out",
    "build",
    ".venv",
    "venv",
}

PROJECT_SCOPE_KEYWORDS = {
    "整个项目",
    "项目级",
    "工程级",
    "工作区",
    "多文件",
    "多个文件",
    "项目代码",
    "codebase",
    "workspace",
    "project",
    "multiple files",
    "across files",
}


@dataclass
class WorkspaceFileSnapshot:
    absolute_path: str
    relative_path: str
    reason: str
    score: int
    full_content: str
    excerpt: str

    """
    将候选文件整理为提示词片段。
    """
    def to_prompt_text(self) -> str:
        content_for_prompt = self.full_content if len(self.full_content) <= 6000 else self.excerpt
        content_mode = "full" if content_for_prompt == self.full_content else "excerpt"
        return (
            f"<candidate_file path=\"{self.relative_path}\" score=\"{self.score}\" mode=\"{content_mode}\">\n"
            f"Reason: {self.reason}\n"
            f"{content_for_prompt}\n"
            f"</candidate_file>"
        )


@dataclass
class WorkspaceSearchResult:
    workspace_root: str = ""
    candidate_files: list[WorkspaceFileSnapshot] = field(default_factory=list)
    overview_lines: list[str] = field(default_factory=list)

    """
    将检索结果整理为提示词文本。
    """
    def to_prompt_text(self) -> str:
        if not self.workspace_root:
            return "(workspace unavailable)"

        lines = [f"- Workspace root: {self.workspace_root}"]
        if self.overview_lines:
            lines.append("- Workspace overview:")
            lines.extend(f"  - {line}" for line in self.overview_lines)

        if not self.candidate_files:
            lines.append("- Relevant files: none")
            return "\n".join(lines)

        lines.append("- Relevant file candidates:")
        for snapshot in self.candidate_files:
            lines.append(snapshot.to_prompt_text())
        return "\n".join(lines)


class WorkspaceSearchTool:
    """
    基于请求内容、活动文件和路径特征，挑选更适合送入模型的工作区候选文件。
    """

    def search(self, context: AgentContextModel, prompt: str) -> WorkspaceSearchResult:
        workspace_root = (context.workspaceRoot or "").strip()
        if not workspace_root:
            return WorkspaceSearchResult()

        root = Path(workspace_root)
        if not root.exists() or not root.is_dir():
            return WorkspaceSearchResult()

        candidate_paths = self._collect_candidate_paths(root)
        active_file = Path(context.activeFile).resolve() if context.activeFile else None
        project_scope = self._is_project_scope_request(prompt)
        scored_entries: list[tuple[int, str, Path]] = []

        for path in candidate_paths:
            score, reason = self._score_path(path, root, prompt, active_file, project_scope)
            scored_entries.append((score, reason, path))

        scored_entries.sort(key=lambda item: (-item[0], len(str(item[2]))))
        selected_paths = self._pick_top_paths(scored_entries, root, active_file, project_scope)

        snapshots: list[WorkspaceFileSnapshot] = []
        for score, reason, path in selected_paths:
            content = self._read_text(path)
            if not content:
                continue

            relative_path = self._to_relative(root, path)
            excerpt = self._build_excerpt(content, 1800)
            snapshots.append(
                WorkspaceFileSnapshot(
                    absolute_path=str(path),
                    relative_path=relative_path,
                    reason=reason,
                    score=score,
                    full_content=content,
                    excerpt=excerpt,
                )
            )

        overview_lines = [self._to_relative(root, path) for _, _, path in scored_entries[:15]]
        return WorkspaceSearchResult(
            workspace_root=str(root),
            candidate_files=snapshots,
            overview_lines=overview_lines,
        )

    def _collect_candidate_paths(self, root: Path) -> list[Path]:
        paths: list[Path] = []

        for path in root.rglob("*"):
            if len(paths) >= 650:
                break

            if path.is_dir():
                continue

            if any(part in IGNORED_DIRECTORIES for part in path.parts):
                continue

            if path.suffix.lower() not in TEXT_FILE_SUFFIXES:
                continue

            try:
                if path.stat().st_size > 120_000:
                    continue
            except OSError:
                continue

            paths.append(path)

        return paths

    def _pick_top_paths(
        self,
        scored_entries: list[tuple[int, str, Path]],
        root: Path,
        active_file: Path | None,
        project_scope: bool,
    ) -> list[tuple[int, str, Path]]:
        selected: list[tuple[int, str, Path]] = []
        deferred: list[tuple[int, str, Path]] = []
        seen: set[str] = set()
        selected_directory_counts: dict[str, int] = {}
        max_files = 9 if project_scope else 6

        if active_file and active_file.exists() and not project_scope:
            active_key = str(active_file.resolve())
            for score, reason, path in scored_entries:
                if str(path.resolve()) == active_key:
                    selected.append((max(score, 120), "当前活动文件", path))
                    seen.add(active_key)
                    selected_directory_counts[str(path.parent.resolve())] = 1
                    break

        for score, reason, path in scored_entries:
            resolved = str(path.resolve())
            if resolved in seen:
                continue

            if len(selected) >= max_files:
                break

            if score <= 0 and selected:
                continue

            directory_key = str(path.parent.resolve())
            if project_scope and selected_directory_counts.get(directory_key, 0) >= 2:
                deferred.append((score, reason, path))
                continue

            selected.append((score, reason, path))
            seen.add(resolved)
            selected_directory_counts[directory_key] = selected_directory_counts.get(directory_key, 0) + 1

        for score, reason, path in deferred:
            resolved = str(path.resolve())
            if resolved in seen or len(selected) >= max_files:
                continue

            selected.append((score, reason, path))
            seen.add(resolved)

        if not selected:
            fallback_paths = [
                root / "README.md",
                root / "backend" / "service.py",
                root / "src" / "extension.ts",
            ]
            for path in fallback_paths:
                if path.exists():
                    selected.append((10, "默认关键文件", path))

        return selected

    def _score_path(
        self,
        path: Path,
        root: Path,
        prompt: str,
        active_file: Path | None,
        project_scope: bool,
    ) -> tuple[int, str]:
        prompt_lower = prompt.lower()
        relative_path = self._to_relative(root, path).replace("\\", "/").lower()
        file_name = path.name.lower()
        score = 0
        reasons: list[str] = []

        if active_file and path.resolve() == active_file:
            active_bonus = 40 if project_scope else 120
            score += active_bonus
            reasons.append("当前活动文件")
        elif active_file and path.parent == active_file.parent:
            sibling_bonus = 10 if project_scope else 18
            score += sibling_bonus
            reasons.append("与当前活动文件位于同一目录")

        english_terms = set(re.findall(r"[a-zA-Z_][a-zA-Z0-9_./-]{2,}", prompt_lower))
        for term in sorted(english_terms):
            if term in relative_path:
                score += 12
                reasons.append(f"路径命中关键词 {term}")

        if mentions_documentation(prompt) and (
            relative_path == "readme.md"
            or relative_path.startswith("docs/")
            or path.suffix.lower() in {".md", ".txt"}
        ):
            score += 32
            reasons.append("与文档更新需求相关")

        if any(keyword in prompt_lower for keyword in ["后端", "python", "ollama", "service", "agent"]):
            if relative_path.startswith("backend/"):
                score += 24
                reasons.append("与后端或 Agent 逻辑相关")

        if any(keyword in prompt_lower for keyword in ["前端", "界面", "插件", "vscode", "webview", "panel", "ui"]):
            if relative_path.startswith("src/") or relative_path.startswith("media/") or relative_path.startswith("webview-src/"):
                score += 24
                reasons.append("与插件界面相关")

        if any(keyword in prompt_lower for keyword in ["配置", "依赖", "环境", "requirements", "package", "conda", "lora", "model"]):
            if file_name in {"package.json", "requirements.txt", "environment.yml", "model_profiles.json"}:
                score += 24
                reasons.append("与项目配置相关")

        if project_scope and path.suffix.lower() in {".py", ".ts", ".tsx", ".js", ".md", ".json"}:
            score += 6
            reasons.append("适合作为项目级上下文")

        if relative_path == "readme.md":
            score += 8
            reasons.append("项目入口说明文件")

        if relative_path.startswith("docs/"):
            score += 6
            reasons.append("文档目录")

        if not reasons:
            reasons.append("工作区候选文件")

        return score, "；".join(reasons[:3])

    def _read_text(self, path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            try:
                return path.read_text(encoding="gbk")
            except UnicodeDecodeError:
                return path.read_text(errors="ignore")
        except OSError:
            return ""

    def _build_excerpt(self, content: str, max_chars: int) -> str:
        cleaned = content.strip()
        if len(cleaned) <= max_chars:
            return cleaned
        return cleaned[:max_chars] + "\n...[truncated by workspace search]"

    def _to_relative(self, root: Path, path: Path) -> str:
        try:
            return str(path.resolve().relative_to(root.resolve()))
        except ValueError:
            return str(path)

    def _is_project_scope_request(self, prompt: str) -> bool:
        normalized = prompt.strip().lower()
        return any(keyword in normalized for keyword in PROJECT_SCOPE_KEYWORDS)
