import ast
from dataclasses import dataclass, field
from pathlib import Path

from backend.models import AgentContextModel, FileActionModel
from backend.structured_response import ParsedAction
from backend.tools.workspace_search_tool import WorkspaceSearchResult


@dataclass
class WorkspaceActionPreparationResult:
    """保存动作校验后的结果。"""

    actions: list[FileActionModel] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


class WorkspaceActionTool:
    """对多文件动作做安全校验，并补齐 originalContent。"""

    def prepare_actions(
        self,
        context: AgentContextModel,
        parsed_actions: list[ParsedAction],
        search_result: WorkspaceSearchResult,
    ) -> WorkspaceActionPreparationResult:
        workspace_root = (context.workspaceRoot or "").strip()
        if not workspace_root:
            return WorkspaceActionPreparationResult(notes=["当前工作区不可用，无法准备多文件变更方案。"])

        root = Path(workspace_root).resolve()
        candidate_map = {
            snapshot.relative_path.replace("\\", "/"): snapshot
            for snapshot in search_result.candidate_files
        }

        prepared_actions: list[FileActionModel] = []
        notes: list[str] = []

        for parsed_action in parsed_actions[:6]:
            resolved_path = self._resolve_target_path(root, parsed_action.target_file)
            if resolved_path is None:
                notes.append(f"已忽略越界路径：{parsed_action.target_file}")
                continue

            original_content = self._read_original_content(
                context=context,
                target_path=resolved_path,
                candidate_map=candidate_map,
            )

            validation_error = self._validate_action(parsed_action, resolved_path, original_content)
            if validation_error:
                notes.append(f"{resolved_path.name}：{validation_error}")
                continue

            prepared_actions.append(
                FileActionModel(
                    kind=parsed_action.kind,
                    targetFile=str(resolved_path),
                    originalContent=original_content,
                    updatedContent=parsed_action.updated_content,
                    summary=parsed_action.summary or self._default_summary(parsed_action.kind, resolved_path),
                )
            )

        return WorkspaceActionPreparationResult(actions=prepared_actions, notes=notes)

    def _resolve_target_path(self, root: Path, target_file: str) -> Path | None:
        if not target_file.strip():
            return None

        candidate = Path(target_file)
        if not candidate.is_absolute():
            candidate = root / candidate

        try:
            resolved = candidate.resolve()
            resolved.relative_to(root)
        except (OSError, ValueError):
            return None

        return resolved

    def _read_original_content(
        self,
        context: AgentContextModel,
        target_path: Path,
        candidate_map: dict[str, object],
    ) -> str:
        normalized_relative = str(target_path).replace("\\", "/")

        if context.activeFile and Path(context.activeFile).resolve() == target_path and context.fullDocumentText:
            return context.fullDocumentText

        relative_key = normalized_relative
        if context.workspaceRoot:
            try:
                relative_key = str(target_path.relative_to(Path(context.workspaceRoot).resolve())).replace("\\", "/")
            except ValueError:
                relative_key = normalized_relative

        snapshot = candidate_map.get(relative_key)
        if snapshot is not None:
            return snapshot.full_content  # type: ignore[attr-defined]

        if not target_path.exists():
            return ""

        try:
            return target_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            try:
                return target_path.read_text(encoding="gbk")
            except UnicodeDecodeError:
                return target_path.read_text(errors="ignore")
        except OSError:
            return ""

    def _validate_action(self, parsed_action: ParsedAction, target_path: Path, original_content: str) -> str | None:
        updated_content = parsed_action.updated_content.strip()
        if not updated_content:
            return "模型没有返回完整的新文件内容。"

        if parsed_action.kind == "create_file":
            if target_path.exists():
                return "目标文件已经存在，当前动作类型不适合创建文件。"
            if self._is_python_file(target_path):
                syntax_error = self._validate_python_syntax(updated_content)
                if syntax_error:
                    return syntax_error
            return None

        if parsed_action.kind == "update_file":
            if not target_path.exists():
                return "目标文件不存在，无法按 update_file 处理。"
            if self._canonicalize(updated_content) == self._canonicalize(original_content):
                return "更新后内容与原文件一致，因此无需修改。"
            if self._is_python_file(target_path):
                syntax_error = self._validate_python_syntax(updated_content)
                if syntax_error:
                    return syntax_error
            return None

        if parsed_action.kind == "update_documentation":
            if not self._is_documentation_file(target_path):
                return "目标路径不像文档文件，文档动作应优先指向 README.md 或 docs/*.md。"
            if self._canonicalize(updated_content) == self._canonicalize(original_content):
                return "文档更新内容与原文件一致，因此无需修改。"
            return None

        return "未知动作类型。"

    def _is_python_file(self, target_path: Path) -> bool:
        return target_path.suffix.lower() == ".py"

    def _is_documentation_file(self, target_path: Path) -> bool:
        normalized = str(target_path).replace("\\", "/").lower()
        return (
            normalized.endswith(".md")
            or normalized.endswith(".txt")
            or normalized.endswith(".rst")
            or "/docs/" in normalized
            or normalized.endswith("/readme.md")
            or normalized.endswith("readme.md")
        )

    def _validate_python_syntax(self, content: str) -> str | None:
        try:
            ast.parse(content)
        except SyntaxError as exc:
            return f"模型生成的 Python 代码存在语法错误，大约在第 {exc.lineno} 行。"
        return None

    def _canonicalize(self, content: str) -> str:
        return content.replace("\r\n", "\n").replace("\r", "\n").strip()

    def _default_summary(self, kind: str, target_path: Path) -> str:
        if kind == "create_file":
            return f"新增文件 {target_path.name}"
        if kind == "update_documentation":
            return f"更新文档 {target_path.name}"
        return f"修改文件 {target_path.name}"
