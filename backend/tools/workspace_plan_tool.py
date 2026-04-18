import re
from dataclasses import dataclass, field
from pathlib import Path

from backend.models import AgentActionKind, AgentContextModel
from backend.request_classifier import mentions_documentation
from backend.tools.workspace_search_tool import WorkspaceSearchResult

# 文件说明：
# 本文件在结构化输出不稳定时，先用规则方式规划一组更可信的目标文件。
# 该规划结果会作为后续逐文件改写的输入，因此重点是“范围合理”和“路径稳定”。

DOCUMENTATION_SUFFIXES = {".md", ".rst", ".txt"}
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
class PlannedWorkspaceAction:
    kind: AgentActionKind
    target_file: str
    summary: str
    rationale: str = ""


@dataclass
class WorkspacePlanResult:
    actions: list[PlannedWorkspaceAction] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


class WorkspacePlanTool:
    """
    在弱模型场景下为项目级请求先挑出更值得修改的目标文件。
    """

    def plan(
        self,
        context: AgentContextModel,
        prompt: str,
        search_result: WorkspaceSearchResult,
    ) -> WorkspacePlanResult:
        workspace_root = (context.workspaceRoot or "").strip()
        if not workspace_root:
            return WorkspacePlanResult(notes=["当前工作区不可用，无法规划项目级修改。"])

        root = Path(workspace_root).resolve()
        normalized_prompt = prompt.strip().lower()
        project_scope = self._is_project_scope_request(normalized_prompt)
        documentation_requested = mentions_documentation(prompt)
        docs_only_request = documentation_requested and not self._mentions_code_change(normalized_prompt)
        create_requested = self._mentions_creation(normalized_prompt)
        max_actions = 5 if project_scope else 3

        candidate_paths = {
            snapshot.relative_path.replace("\\", "/").lower(): snapshot.relative_path.replace("\\", "/")
            for snapshot in search_result.candidate_files
        }
        candidate_file_names = {
            Path(snapshot.relative_path).name.lower(): snapshot.relative_path.replace("\\", "/")
            for snapshot in search_result.candidate_files
        }

        selected: dict[str, PlannedWorkspaceAction] = {}
        notes: list[str] = []

        for explicit_path in self._extract_explicit_paths(prompt):
            normalized_path = explicit_path.lower()
            relative_path = candidate_paths.get(
                normalized_path,
                candidate_file_names.get(Path(explicit_path).name.lower(), explicit_path),
            )
            target_path = root / relative_path

            if target_path.exists():
                kind = "update_documentation" if self._is_documentation_path(relative_path) else "update_file"
            elif self._is_documentation_path(relative_path):
                kind = "update_documentation"
            elif create_requested:
                kind = "create_file"
            else:
                notes.append(f"检测到显式路径 {relative_path}，但目标文件当前不存在，因此暂不纳入动作方案。")
                continue

            self._add_action(
                selected,
                PlannedWorkspaceAction(
                    kind=kind,
                    target_file=relative_path,
                    summary=self._build_summary(kind, relative_path, context),
                    rationale="用户请求中显式提到了该文件。",
                ),
            )

        if not docs_only_request and not project_scope:
            active_relative = self._active_file_relative_path(context, root)
            if active_relative:
                self._add_action(
                    selected,
                    PlannedWorkspaceAction(
                        kind="update_file",
                        target_file=active_relative,
                        summary=self._build_summary("update_file", active_relative, context),
                        rationale="当前请求更接近当前文件改写，因此优先保留活动文件。",
                    ),
                )

        if documentation_requested and not self._documentation_is_optional(normalized_prompt):
            documentation_target = self._pick_documentation_target(root, search_result)
            if documentation_target:
                self._add_action(
                    selected,
                    PlannedWorkspaceAction(
                        kind="update_documentation",
                        target_file=documentation_target,
                        summary=self._build_summary("update_documentation", documentation_target, context),
                        rationale="请求中包含明确的文档更新意图。",
                    ),
                )

        self._add_ranked_code_candidates(
            selected=selected,
            search_result=search_result,
            context=context,
            max_actions=max_actions,
            include_active=True,
        )

        return WorkspacePlanResult(actions=list(selected.values())[:max_actions], notes=notes)

    def _add_action(
        self,
        selected: dict[str, PlannedWorkspaceAction],
        action: PlannedWorkspaceAction,
    ) -> None:
        key = action.target_file.replace("\\", "/").lower()
        if key not in selected:
            selected[key] = action

    def _extract_explicit_paths(self, prompt: str) -> list[str]:
        matches = re.findall(r"[A-Za-z0-9_./\\\\-]+\.[A-Za-z0-9]+", prompt)
        cleaned: list[str] = []

        for match in matches:
            normalized = match.strip(" \t\r\n,.;:，。；：)[]{}<>").replace("\\", "/")
            if not normalized:
                continue
            if normalized.lower() not in {item.lower() for item in cleaned}:
                cleaned.append(normalized)

        return cleaned

    def _mentions_creation(self, normalized_prompt: str) -> bool:
        keywords = ["新建", "新增", "创建", "create", "add", "new file"]
        return any(keyword in normalized_prompt for keyword in keywords)

    def _mentions_code_change(self, normalized_prompt: str) -> bool:
        keywords = [
            "代码",
            "功能",
            "修复",
            "优化",
            "重构",
            "实现",
            "bug",
            "class",
            "function",
            "python",
            "backend",
            "插件",
            "webview",
            ".py",
            ".ts",
            ".tsx",
            ".js",
        ]
        return any(keyword in normalized_prompt for keyword in keywords)

    def _documentation_is_optional(self, normalized_prompt: str) -> bool:
        optional_markers = ["必要时", "如果需要", "视情况", "可选", "if needed", "if necessary", "optionally"]
        return any(marker in normalized_prompt for marker in optional_markers)

    def _active_file_relative_path(self, context: AgentContextModel, root: Path) -> str | None:
        if not context.activeFile:
            return None

        try:
            return str(Path(context.activeFile).resolve().relative_to(root)).replace("\\", "/")
        except ValueError:
            return None

    def _pick_documentation_target(self, root: Path, search_result: WorkspaceSearchResult) -> str | None:
        readme_path = root / "README.md"
        if readme_path.exists():
            return "README.md"

        for snapshot in search_result.candidate_files:
            relative_path = snapshot.relative_path.replace("\\", "/")
            if self._is_documentation_path(relative_path):
                return relative_path

        docs_readme = root / "docs" / "README.md"
        if docs_readme.exists():
            return "docs/README.md"

        return None

    def _is_documentation_path(self, relative_path: str) -> bool:
        normalized = relative_path.replace("\\", "/").lower()
        suffix = Path(normalized).suffix.lower()
        return (
            normalized == "readme.md"
            or normalized.startswith("docs/")
            or suffix in DOCUMENTATION_SUFFIXES
        )

    def _build_summary(
        self,
        kind: AgentActionKind,
        relative_path: str,
        context: AgentContextModel,
    ) -> str:
        active_relative = ""
        if context.workspaceRoot and context.activeFile:
            try:
                active_relative = str(
                    Path(context.activeFile).resolve().relative_to(Path(context.workspaceRoot).resolve())
                ).replace("\\", "/")
            except ValueError:
                active_relative = ""

        if kind == "create_file":
            return f"新增文件：{relative_path}"

        if kind == "update_documentation":
            return f"同步更新文档：{relative_path}"

        if active_relative and active_relative.lower() == relative_path.lower():
            return f"根据当前需求优化活动文件：{relative_path}"

        return f"根据项目上下文更新相关文件：{relative_path}"

    def _add_ranked_code_candidates(
        self,
        selected: dict[str, PlannedWorkspaceAction],
        search_result: WorkspaceSearchResult,
        context: AgentContextModel,
        max_actions: int,
        include_active: bool,
    ) -> None:
        directory_counts: dict[str, int] = {}

        for action in selected.values():
            directory = str(Path(action.target_file).parent).replace("\\", "/")
            directory_counts[directory] = directory_counts.get(directory, 0) + 1

        active_relative = ""
        if context.workspaceRoot and context.activeFile:
            try:
                active_relative = str(
                    Path(context.activeFile).resolve().relative_to(Path(context.workspaceRoot).resolve())
                ).replace("\\", "/").lower()
            except ValueError:
                active_relative = ""

        for snapshot in search_result.candidate_files:
            if len(selected) >= max_actions:
                break

            relative_path = snapshot.relative_path.replace("\\", "/")
            normalized_relative = relative_path.lower()
            if self._is_documentation_path(relative_path):
                continue
            if not include_active and normalized_relative == active_relative:
                continue

            directory = str(Path(relative_path).parent).replace("\\", "/")
            if directory not in {"", "."} and directory_counts.get(directory, 0) >= 2:
                continue

            self._add_action(
                selected,
                PlannedWorkspaceAction(
                    kind="update_file",
                    target_file=relative_path,
                    summary=self._build_summary("update_file", relative_path, context),
                    rationale="该文件在工作区检索结果中得分较高，适合作为项目级修改目标。",
                ),
            )

            directory_counts[directory] = directory_counts.get(directory, 0) + 1

    def _is_project_scope_request(self, normalized_prompt: str) -> bool:
        return any(keyword in normalized_prompt for keyword in PROJECT_SCOPE_KEYWORDS)
