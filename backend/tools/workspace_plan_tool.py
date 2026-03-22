import re
from dataclasses import dataclass, field
from pathlib import Path

from backend.models import AgentActionKind, AgentContextModel
from backend.request_classifier import mentions_documentation
from backend.tools.workspace_search_tool import WorkspaceSearchResult

# 文件说明：
# 本文件负责在模型结构化输出不稳定时，使用规则化方式规划候选动作。
# 它不是最终执行器，而是为“逐文件改写模式”提供稳定的目标文件集合。

DOCUMENTATION_SUFFIXES = {".md", ".rst", ".txt"}


# 数据说明：
# 表示一个规则化规划得到的候选动作。
@dataclass
class PlannedWorkspaceAction:
    kind: AgentActionKind
    target_file: str
    summary: str
    rationale: str = ""


# 数据说明：
# 表示规则化规划阶段的整体结果。
@dataclass
class WorkspacePlanResult:
    actions: list[PlannedWorkspaceAction] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


# 类说明：
# 负责在弱模型条件下，为项目级修改先挑出更可能需要修改的文件。
class WorkspacePlanTool:
    # 方法说明：
    # 基于活动文件、显式路径和请求意图生成候选动作。
    def plan(
        self,
        context: AgentContextModel,
        prompt: str,
        search_result: WorkspaceSearchResult,
    ) -> WorkspacePlanResult:
        workspace_root = (context.workspaceRoot or "").strip()
        if not workspace_root:
            return WorkspacePlanResult(notes=["当前工作区不可用，无法兜底规划项目级修改。"])

        root = Path(workspace_root).resolve()
        normalized_prompt = prompt.strip().lower()
        documentation_requested = mentions_documentation(prompt)
        docs_only_request = documentation_requested and not self._mentions_code_change(normalized_prompt)
        create_requested = self._mentions_creation(normalized_prompt)

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
                notes.append(f"检测到显式路径 {relative_path}，但该文件当前不存在，因此暂不纳入动作方案。")
                continue

            self._add_action(
                selected,
                PlannedWorkspaceAction(
                    kind=kind,
                    target_file=relative_path,
                    summary=self._build_summary(kind, relative_path, context),
                    rationale="用户请求中显式提到了这个文件。",
                ),
            )

        if not docs_only_request:
            active_relative = self._active_file_relative_path(context, root)
            if active_relative:
                self._add_action(
                    selected,
                    PlannedWorkspaceAction(
                        kind="update_file",
                        target_file=active_relative,
                        summary=self._build_summary("update_file", active_relative, context),
                        rationale="当前活动文件通常是本轮修改的第一优先级。",
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
                        rationale="用户请求中包含文档或说明更新意图。",
                    ),
                )

        if len(selected) < 2 and not docs_only_request:
            for snapshot in search_result.candidate_files:
                relative_path = snapshot.relative_path.replace("\\", "/")
                if self._is_documentation_path(relative_path):
                    continue

                self._add_action(
                    selected,
                    PlannedWorkspaceAction(
                        kind="update_file",
                        target_file=relative_path,
                        summary=self._build_summary("update_file", relative_path, context),
                        rationale="它是工作区检索结果中得分较高的代码文件。",
                    ),
                )

                if len(selected) >= 2:
                    break

        return WorkspacePlanResult(actions=list(selected.values())[:3], notes=notes)

    # 方法说明：
    # 将动作加入候选集合，并以目标路径去重。
    def _add_action(
        self,
        selected: dict[str, PlannedWorkspaceAction],
        action: PlannedWorkspaceAction,
    ) -> None:
        key = action.target_file.replace("\\", "/").lower()
        if key not in selected:
            selected[key] = action

    # 方法说明：
    # 从用户请求中提取显式提到的文件路径。
    def _extract_explicit_paths(self, prompt: str) -> list[str]:
        matches = re.findall(r"[A-Za-z0-9_./\\\\-]+\.[A-Za-z0-9]+", prompt)
        cleaned: list[str] = []

        for match in matches:
            normalized = match.strip(" \t\r\n,.;:，。；：()[]{}<>").replace("\\", "/")
            if not normalized:
                continue
            if normalized.lower() not in {item.lower() for item in cleaned}:
                cleaned.append(normalized)

        return cleaned

    # 方法说明：
    # 判断请求中是否显式包含“新建文件”意图。
    def _mentions_creation(self, normalized_prompt: str) -> bool:
        keywords = ["新建", "新增", "创建", "create", "add", "new file"]
        return any(keyword in normalized_prompt for keyword in keywords)

    # 方法说明：
    # 判断请求是否明确指向代码层面的修改，而不只是文档说明。
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

    # 方法说明：
    # 判断请求中提到的文档修改是否只是“可选项”。
    def _documentation_is_optional(self, normalized_prompt: str) -> bool:
        optional_markers = ["必要时", "如果需要", "视情况", "可选", "if needed", "if necessary", "optionally"]
        return any(marker in normalized_prompt for marker in optional_markers)

    # 方法说明：
    # 将当前活动文件转换为相对工作区路径。
    def _active_file_relative_path(self, context: AgentContextModel, root: Path) -> str | None:
        if not context.activeFile:
            return None

        try:
            return str(Path(context.activeFile).resolve().relative_to(root)).replace("\\", "/")
        except ValueError:
            return None

    # 方法说明：
    # 在需要文档动作时，为请求挑选最合适的文档目标文件。
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

    # 方法说明：
    # 判断相对路径是否应视为文档文件。
    def _is_documentation_path(self, relative_path: str) -> bool:
        normalized = relative_path.replace("\\", "/").lower()
        suffix = Path(normalized).suffix.lower()
        return (
            normalized == "readme.md"
            or normalized.startswith("docs/")
            or suffix in DOCUMENTATION_SUFFIXES
        )

    # 方法说明：
    # 为规则化规划生成简洁摘要。
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
