import ast
from dataclasses import dataclass, field
from pathlib import Path

from backend.models import AgentContextModel, FileActionModel
from backend.structured_response import ParsedAction
from backend.tools.workspace_search_tool import WorkspaceSearchResult

# 文件说明：
# 本文件负责将模型动作转换为可执行动作。
# 其核心目标是保证路径安全、内容完整，以及在必要时补齐原始文件内容。


# 数据说明：
# 保存动作预处理后的结果。
@dataclass
class WorkspaceActionPreparationResult:
    actions: list[FileActionModel] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


# 类说明：
# 负责校验结构化动作并补齐执行所需的上下文。
class WorkspaceActionTool:
    # 方法说明：
    # 对解析后的动作集合做统一校验与补全。
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

        for parsed_action in parsed_actions[:8]:
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

    # 方法说明：
    # 将动作中的目标路径解析为工作区内的绝对路径。
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

    # 方法说明：
    # 为动作读取原始文件内容，供 diff 预览和冲突检测使用。
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

    # 方法说明：
    # 针对不同动作类型执行内容和路径校验。
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
            if self._looks_like_source_code(updated_content):
                return "文档动作返回的内容更像源代码，为了安全起见，这次不会直接覆盖文档。"
            if self._canonicalize(updated_content) == self._canonicalize(original_content):
                return "文档更新内容与原文件一致，因此无需修改。"
            return None

        return "未知动作类型。"

    # 方法说明：
    # 判断目标路径是否为 Python 文件。
    def _is_python_file(self, target_path: Path) -> bool:
        return target_path.suffix.lower() == ".py"

    # 方法说明：
    # 判断目标路径是否属于文档文件。
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

    # 方法说明：
    # 使用 AST 校验 Python 内容是否存在明显语法错误。
    def _validate_python_syntax(self, content: str) -> str | None:
        try:
            ast.parse(content)
        except SyntaxError as exc:
            return f"模型生成的 Python 代码存在语法错误，大约在第 {exc.lineno} 行。"
        return None

    # 方法说明：
    # 粗略判断一个“文档动作”是否错误地返回了源码。
    def _looks_like_source_code(self, content: str) -> bool:
        normalized = content.lstrip()
        source_markers = [
            "import ",
            "from ",
            "class ",
            "def ",
            "function ",
            "const ",
            "let ",
            "interface ",
            "public class ",
            "#include ",
        ]

        if any(normalized.startswith(marker) for marker in source_markers):
            return True

        lowered = normalized.lower()
        return "```python" in lowered or "```ts" in lowered or "```javascript" in lowered

    # 方法说明：
    # 统一换行和首尾空白，便于比较文件是否真正发生变化。
    def _canonicalize(self, content: str) -> str:
        return content.replace("\r\n", "\n").replace("\r", "\n").strip()

    # 方法说明：
    # 当模型没有提供摘要时，生成默认摘要。
    def _default_summary(self, kind: str, target_path: Path) -> str:
        if kind == "create_file":
            return f"新增文件 {target_path.name}"
        if kind == "update_documentation":
            return f"更新文档 {target_path.name}"
        return f"修改文件 {target_path.name}"
