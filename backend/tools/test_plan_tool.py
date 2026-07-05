import json
from dataclasses import dataclass, field
from pathlib import Path

from backend.models import AgentContextModel, FileActionModel


@dataclass
class TestCommandPlan:
    """
    描述一条测试或验证命令。
    """

    command: str
    purpose: str
    kind: str = "validation"
    confidence: str = "medium"


@dataclass
class TestPlanResult:
    """
    描述修改完成后的自动测试计划。
    """

    available: bool = False
    summary: str = ""
    commands: list[TestCommandPlan] = field(default_factory=list)
    machine_learning_basis: str = ""
    has_standard_tests: bool = False


class TestPlanTool:
    """
    基于工程目录结构推断修改后的测试与验证命令。
    当前实现属于规则驱动的工程分析，不依赖监督训练数据。
    """

    def build(
        self,
        context: AgentContextModel,
        actions: list[FileActionModel],
    ) -> TestPlanResult:
        workspace_root = self._resolve_workspace_root(context, actions)
        if workspace_root is None or not workspace_root.exists():
            return TestPlanResult(
                available=False,
                summary="未识别出可执行自动测试的工作区根目录。",
                machine_learning_basis="当前测试计划推断采用规则驱动方法，不属于监督学习。",
            )

        commands: list[TestCommandPlan] = []
        has_standard_tests = False

        python_test = self._detect_pytest_command(workspace_root)
        if python_test is not None:
            commands.append(python_test)
            has_standard_tests = True

        node_test_commands = self._detect_node_test_commands(workspace_root)
        if node_test_commands:
            commands.extend(node_test_commands)
            has_standard_tests = True

        if not commands:
            fallback_commands = self._build_fallback_validations(workspace_root)
            commands.extend(fallback_commands)

        available = bool(commands)
        if has_standard_tests:
            summary = (
                f"已检测到 {len(commands)} 条自动测试/验证命令，修改完成后可自动执行。"
            )
        elif available:
            summary = (
                "未检测到标准测试框架，将退化为语法检查与主程序冒烟验证。"
            )
        else:
            summary = "当前工作区未检测到可执行的测试或验证命令。"

        return TestPlanResult(
            available=available,
            summary=summary,
            commands=commands,
            machine_learning_basis=(
                "当前测试计划推断采用规则驱动的工程特征分析，"
                "用于在修改后自动选择测试命令，不属于监督学习。"
            ),
            has_standard_tests=has_standard_tests,
        )

    def _resolve_workspace_root(
        self,
        context: AgentContextModel,
        actions: list[FileActionModel],
    ) -> Path | None:
        if context.workspaceRoot:
            return Path(context.workspaceRoot).resolve()

        if context.activeFile:
            return Path(context.activeFile).resolve().parent

        if actions:
            first_target = Path(actions[0].targetFile).resolve()
            if first_target.is_file():
                return first_target.parent
            return first_target

        return None

    def _detect_pytest_command(self, workspace_root: Path) -> TestCommandPlan | None:
        pytest_markers = [
            workspace_root / "pytest.ini",
            workspace_root / "conftest.py",
            workspace_root / "tests",
        ]
        if any(marker.exists() for marker in pytest_markers):
            return TestCommandPlan(
                command="python -m pytest -q",
                purpose="运行工作区中的 pytest 自动测试。",
                kind="test",
                confidence="high",
            )

        pyproject_path = workspace_root / "pyproject.toml"
        if pyproject_path.exists():
            content = self._safe_read(pyproject_path)
            if "pytest" in content.lower():
                return TestCommandPlan(
                    command="python -m pytest -q",
                    purpose="运行 pyproject.toml 中声明的 pytest 自动测试。",
                    kind="test",
                    confidence="high",
                )

        for dependency_file in ("requirements.txt", "environment.yml"):
            candidate = workspace_root / dependency_file
            if candidate.exists() and "pytest" in self._safe_read(candidate).lower():
                return TestCommandPlan(
                    command="python -m pytest -q",
                    purpose="运行依赖配置中推断出的 pytest 自动测试。",
                    kind="test",
                    confidence="medium",
                )

        return None

    def _detect_node_test_commands(self, workspace_root: Path) -> list[TestCommandPlan]:
        package_json = workspace_root / "package.json"
        if not package_json.exists():
            return []

        try:
            package_data = json.loads(self._safe_read(package_json))
        except json.JSONDecodeError:
            return []

        scripts = package_data.get("scripts", {})
        if not isinstance(scripts, dict) or "test" not in scripts:
            return []

        command_prefix = "npm"
        if (workspace_root / "pnpm-lock.yaml").exists():
            command_prefix = "pnpm"
        elif (workspace_root / "yarn.lock").exists():
            command_prefix = "yarn"

        return [
            TestCommandPlan(
                command=f"{command_prefix} test",
                purpose="运行 package.json 中定义的测试脚本。",
                kind="test",
                confidence="high",
            )
        ]

    def _build_fallback_validations(self, workspace_root: Path) -> list[TestCommandPlan]:
        commands: list[TestCommandPlan] = []

        if self._looks_like_python_workspace(workspace_root):
            commands.append(
                TestCommandPlan(
                    command="python -m compileall .",
                    purpose="对当前工作区执行 Python 语法级验证。",
                    kind="validation",
                    confidence="high",
                )
            )

            main_file = workspace_root / "main.py"
            if main_file.exists():
                commands.append(
                    TestCommandPlan(
                        command="python main.py",
                        purpose="执行主程序进行一次轻量冒烟验证。",
                        kind="validation",
                        confidence="medium",
                    )
                )

        if not commands and (workspace_root / "package.json").exists():
            commands.append(
                TestCommandPlan(
                    command="npm run build",
                    purpose="执行前端或插件构建，验证项目是否可正常编译。",
                    kind="validation",
                    confidence="medium",
                )
            )

        return commands

    def _looks_like_python_workspace(self, workspace_root: Path) -> bool:
        markers = [
            workspace_root / "requirements.txt",
            workspace_root / "environment.yml",
            workspace_root / "pyproject.toml",
            workspace_root / "main.py",
        ]
        if any(marker.exists() for marker in markers):
            return True

        return any(candidate.suffix == ".py" for candidate in workspace_root.iterdir() if candidate.is_file())

    def _safe_read(self, file_path: Path) -> str:
        try:
            return file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            try:
                return file_path.read_text(encoding="gbk")
            except UnicodeDecodeError:
                return file_path.read_text(errors="ignore")
