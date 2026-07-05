import re
from dataclasses import dataclass, field
from pathlib import Path

from backend.models import AgentContextModel, FileActionModel
from backend.tools.test_plan_tool import TestPlanResult

SIGNATURE_PATTERN = re.compile(
    r"^\s*(def|class|async def|function|interface|type)\s+",
    re.MULTILINE,
)
IMPORT_PATTERN = re.compile(r"^\s*(import|from)\s+", re.MULTILINE)
CODE_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".jsx", ".json", ".yaml", ".yml", ".toml"}


@dataclass
class ActionRiskAssessment:
    """
    描述单个文件动作的风险评估结果。
    """

    target_file: str
    score: int
    level: str
    reason: str
    highlights: list[str] = field(default_factory=list)


@dataclass
class ActionRiskSummary:
    """
    描述一组动作的整体风险评估结果。
    """

    overall_score: int = 0
    overall_level: str = "low"
    overall_reason: str = ""
    highlights: list[str] = field(default_factory=list)
    assessments: list[ActionRiskAssessment] = field(default_factory=list)


class ActionRiskTool:
    """
    基于规则和工程特征对待确认文件动作做风险评估。
    当前实现使用特征工程与规则评分，不依赖监督训练数据。
    """

    def assess(
        self,
        actions: list[FileActionModel],
        context: AgentContextModel,
        test_plan: TestPlanResult | None = None,
    ) -> ActionRiskSummary:
        if not actions:
            return ActionRiskSummary()

        directories = {
            str(Path(action.targetFile).resolve().parent).lower()
            for action in actions
        }
        assessments: list[ActionRiskAssessment] = []

        for action in actions:
            score, reasons, highlights = self._score_action(
                action=action,
                context=context,
                action_count=len(actions),
                directory_count=len(directories),
            )
            assessments.append(
                ActionRiskAssessment(
                    target_file=action.targetFile,
                    score=score,
                    level=self._level_from_score(score),
                    reason="；".join(reasons[:3]),
                    highlights=highlights[:4],
                )
            )

        overall_score = min(
            100,
            max(assessment.score for assessment in assessments)
            + max(0, len(actions) - 1) * 6
            + max(0, len(directories) - 1) * 4,
        )
        summary_highlights = self._build_highlights(actions, assessments, len(directories), test_plan)
        overall_score += self._score_test_readiness(test_plan)
        overall_score = min(100, overall_score)
        overall_level = self._level_from_score(overall_score)
        overall_reason = self._build_overall_reason(actions, assessments, len(directories), test_plan)

        return ActionRiskSummary(
            overall_score=overall_score,
            overall_level=overall_level,
            overall_reason=overall_reason,
            highlights=summary_highlights[:6],
            assessments=assessments,
        )

    def _score_action(
        self,
        action: FileActionModel,
        context: AgentContextModel,
        action_count: int,
        directory_count: int,
    ) -> tuple[int, list[str], list[str]]:
        score = 0
        reasons: list[str] = []
        highlights: list[str] = []
        target_path = Path(action.targetFile)
        suffix = target_path.suffix.lower()
        original_content = action.originalContent or ""
        updated_content = action.updatedContent or ""

        if action.kind == "create_file":
            score += 18
            reasons.append("包含新增文件")
            highlights.append(f"新增文件：{target_path.name}")
        elif action.kind == "update_documentation":
            score += 4
            reasons.append("当前动作主要修改文档")
        else:
            score += 8
            reasons.append("包含现有文件改写")

        if suffix in CODE_SUFFIXES:
            score += 10
            reasons.append("目标是源代码或配置文件")

        if action_count > 1:
            score += min(18, (action_count - 1) * 6)
            reasons.append(f"本次方案涉及 {action_count} 个文件")
            highlights.append(f"涉及 {action_count} 个文件")

        if directory_count > 1:
            score += 8
            reasons.append("修改跨越多个目录")
            highlights.append("跨目录修改")

        if self._has_signature_change(original_content, updated_content):
            score += 20
            reasons.append("检测到函数或类型签名变化")
            highlights.append(f"{target_path.name} 存在接口变更")

        if self._has_import_change(original_content, updated_content):
            score += 10
            reasons.append("检测到导入关系变化")
            highlights.append(f"{target_path.name} 存在依赖变更")

        if self._has_large_content_delta(original_content, updated_content):
            score += 12
            reasons.append("文件改动规模较大")
            highlights.append(f"{target_path.name} 改动规模较大")

        active_file = (context.activeFile or "").strip().lower()
        if active_file and active_file != str(target_path).lower():
            score += 6
            reasons.append("目标文件不是当前活动文件")

        if action.kind == "update_documentation":
            score = max(0, score - 8)

        return min(100, score), reasons, highlights

    def _score_test_readiness(self, test_plan: TestPlanResult | None) -> int:
        if test_plan is None:
            return 8
        if not test_plan.available:
            return 14
        if not test_plan.has_standard_tests:
            return 12
        return 0

    def _build_highlights(
        self,
        actions: list[FileActionModel],
        assessments: list[ActionRiskAssessment],
        directory_count: int,
        test_plan: TestPlanResult | None,
    ) -> list[str]:
        highlights: list[str] = []
        if len(actions) > 1:
            highlights.append(f"多文件修改：{len(actions)} 个文件")
        if directory_count > 1:
            highlights.append("修改范围跨越多个目录")
        if any("接口变更" in highlight for assessment in assessments for highlight in assessment.highlights):
            highlights.append("包含函数或类型接口变更")
        if test_plan is None or not test_plan.available:
            highlights.append("缺少自动测试或验证命令")
        elif not test_plan.has_standard_tests:
            highlights.append("仅检测到语法检查或冒烟验证")
        else:
            highlights.append(f"可自动执行 {len(test_plan.commands)} 条测试命令")
        return highlights

    def _has_signature_change(self, original_content: str, updated_content: str) -> bool:
        return (
            len(SIGNATURE_PATTERN.findall(original_content))
            != len(SIGNATURE_PATTERN.findall(updated_content))
        )

    def _has_import_change(self, original_content: str, updated_content: str) -> bool:
        return (
            len(IMPORT_PATTERN.findall(original_content))
            != len(IMPORT_PATTERN.findall(updated_content))
        )

    def _has_large_content_delta(self, original_content: str, updated_content: str) -> bool:
        original_lines = self._line_count(original_content)
        updated_lines = self._line_count(updated_content)
        delta = abs(updated_lines - original_lines)

        if original_lines == 0:
            return updated_lines >= 30

        if delta >= 40:
            return True

        return delta / max(original_lines, 1) >= 0.35

    def _line_count(self, content: str) -> int:
        normalized = content.replace("\r\n", "\n").replace("\r", "\n").strip()
        if not normalized:
            return 0
        return len(normalized.split("\n"))

    def _level_from_score(self, score: int) -> str:
        if score >= 65:
            return "high"
        if score >= 30:
            return "medium"
        return "low"

    def _build_overall_reason(
        self,
        actions: list[FileActionModel],
        assessments: list[ActionRiskAssessment],
        directory_count: int,
        test_plan: TestPlanResult | None,
    ) -> str:
        reasons: list[str] = []
        if len(actions) > 1:
            reasons.append(f"涉及 {len(actions)} 个文件")
        if directory_count > 1:
            reasons.append("覆盖多个目录")
        if any(assessment.level == "high" for assessment in assessments):
            reasons.append("至少一个文件属于高风险改写")
        if any("签名变化" in assessment.reason for assessment in assessments):
            reasons.append("存在接口或结构定义变化")
        if test_plan is None or not test_plan.available:
            reasons.append("缺少自动测试支撑")
        elif not test_plan.has_standard_tests:
            reasons.append("当前仅能执行验证级检查")
        else:
            reasons.append("修改后可自动执行测试")

        if not reasons:
            reasons.append("本次修改范围较集中")

        return "；".join(reasons[:4])
