import ast
from dataclasses import dataclass, field
from pathlib import Path

from backend.models import AgentContextModel


@dataclass
class CurrentFileReport:
    """保存“当前文件分析工具”的输出结果。"""

    file_path: str = "(none)"
    language_id: str = "(unknown)"
    source_from: str = "unknown"
    line_count: int = 0
    char_count: int = 0
    structure_points: list[str] = field(default_factory=list)
    risk_points: list[str] = field(default_factory=list)
    excerpt: str = ""

    def to_prompt_text(self) -> str:
        lines = [
            f"- File path: {self.file_path}",
            f"- Language id: {self.language_id}",
            f"- Source chosen by tool: {self.source_from}",
            f"- Line count: {self.line_count}",
            f"- Character count: {self.char_count}",
        ]

        if self.structure_points:
            lines.append("- Structural observations:")
            lines.extend(f"  - {item}" for item in self.structure_points)
        else:
            lines.append("- Structural observations: none")

        if self.risk_points:
            lines.append("- Potential risks or refactor hints:")
            lines.extend(f"  - {item}" for item in self.risk_points)
        else:
            lines.append("- Potential risks or refactor hints: none")

        if self.excerpt:
            lines.append("- Tool excerpt:")
            lines.append(self.excerpt)

        return "\n".join(lines)


class CurrentFileTool:
    """读取和分析当前活动文件。"""

    def inspect(self, context: AgentContextModel) -> CurrentFileReport:
        report = CurrentFileReport(
            file_path=context.activeFile or "(none)",
            language_id=context.languageId or "(unknown)",
        )

        source_text, source_from = self._resolve_source_text(context)
        if not source_text:
            report.risk_points.append("当前没有读取到文件内容，模型只能基于用户问题做一般性回答。")
            return report

        report.source_from = source_from
        report.line_count = len(source_text.splitlines())
        report.char_count = len(source_text)
        report.excerpt = self._build_excerpt(source_text)

        if self._is_python_file(context):
            self._analyze_python_source(source_text, report)
        else:
            self._analyze_generic_source(source_text, report)

        return report

    def _resolve_source_text(self, context: AgentContextModel) -> tuple[str, str]:
        if context.fullDocumentText:
            return context.fullDocumentText, "full editor document"

        if context.documentText:
            return context.documentText, "editor excerpt"

        disk_text = self._read_active_file(context.activeFile)
        if disk_text:
            return disk_text, "disk file"

        return "", "unknown"

    def _read_active_file(self, file_path: str | None) -> str:
        if not file_path:
            return ""

        path = Path(file_path)
        if not path.exists() or not path.is_file():
            return ""

        try:
            return path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            try:
                return path.read_text(encoding="gbk")
            except UnicodeDecodeError:
                return path.read_text(errors="ignore")
        except OSError:
            return ""

    def _is_python_file(self, context: AgentContextModel) -> bool:
        if context.languageId == "python":
            return True
        if context.activeFile and context.activeFile.lower().endswith(".py"):
            return True
        return False

    def _build_excerpt(self, source_text: str, max_chars: int = 1200) -> str:
        cleaned = source_text.strip()
        if len(cleaned) <= max_chars:
            return cleaned
        return cleaned[:max_chars] + "\n...[truncated by tool]"

    def _analyze_generic_source(self, source_text: str, report: CurrentFileReport) -> None:
        report.structure_points.append("当前文件不是 Python 文件，因此只做基础文本级分析。")

        if "TODO" in source_text or "FIXME" in source_text:
            report.risk_points.append("文件中包含 TODO 或 FIXME，说明仍有未完成事项。")

        if len(source_text.splitlines()) > 220:
            report.risk_points.append("文件行数较多，后续可以考虑拆分模块。")

    def _analyze_python_source(self, source_text: str, report: CurrentFileReport) -> None:
        try:
            tree = ast.parse(source_text)
        except SyntaxError as exc:
            report.risk_points.append(
                f"当前 Python 代码无法被 AST 正常解析，可能存在语法问题：line {exc.lineno}"
            )
            return

        imports: list[str] = []
        functions: list[str] = []
        classes: list[str] = []
        long_functions: list[str] = []
        broad_excepts: list[str] = []
        print_heavy_functions: list[str] = []

        for node in tree.body:
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.append(node.module or "(relative)")
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                functions.append(node.name)
                self._check_function_quality(node, long_functions, broad_excepts, print_heavy_functions)
            elif isinstance(node, ast.ClassDef):
                classes.append(node.name)
                for child in node.body:
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        functions.append(f"{node.name}.{child.name}")
                        self._check_function_quality(child, long_functions, broad_excepts, print_heavy_functions)

        if imports:
            report.structure_points.append(f"导入模块：{', '.join(imports[:8])}")
        if classes:
            report.structure_points.append(f"类结构：{', '.join(classes[:8])}")
        if functions:
            report.structure_points.append(f"函数/方法：{', '.join(functions[:12])}")
        if not classes and not functions:
            report.structure_points.append("当前文件主要由脚本代码组成，没有明显的类或函数封装。")

        if "TODO" in source_text or "FIXME" in source_text:
            report.risk_points.append("文件中包含 TODO 或 FIXME，说明还有待完成的逻辑。")

        if report.line_count > 220:
            report.risk_points.append("文件整体偏长，可以考虑把不同职责拆到多个模块。")

        if long_functions:
            report.risk_points.append(f"这些函数偏长，建议拆分：{', '.join(long_functions[:6])}")

        if broad_excepts:
            report.risk_points.append(
                f"这些函数使用了宽泛异常捕获，建议更精确处理：{', '.join(broad_excepts[:6])}"
            )

        if print_heavy_functions:
            report.risk_points.append(
                f"这些函数包含较多 print，后续可考虑统一日志或输出层：{', '.join(print_heavy_functions[:6])}"
            )

    def _check_function_quality(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        long_functions: list[str],
        broad_excepts: list[str],
        print_heavy_functions: list[str],
    ) -> None:
        end_lineno = getattr(node, "end_lineno", node.lineno)
        function_length = end_lineno - node.lineno + 1
        if function_length >= 25:
            long_functions.append(f"{node.name}({function_length} lines)")

        has_broad_except = any(
            isinstance(child, ast.ExceptHandler)
            and (
                child.type is None
                or (isinstance(child.type, ast.Name) and child.type.id == "Exception")
            )
            for child in ast.walk(node)
        )
        if has_broad_except:
            broad_excepts.append(node.name)

        print_count = sum(
            1
            for child in ast.walk(node)
            if isinstance(child, ast.Call)
            and isinstance(child.func, ast.Name)
            and child.func.id == "print"
        )
        if print_count >= 3:
            print_heavy_functions.append(f"{node.name}({print_count} prints)")
