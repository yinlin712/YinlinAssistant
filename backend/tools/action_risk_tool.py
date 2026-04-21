import re
from dataclasses import dataclass, field
from pathlib import Path

from backend.models import AgentContextModel, FileActionModel

# 文件说明：
# 本文件负责对待确认文件动作做风险评分。
# 当前实现采用特征工程与规则评分，并不依赖监督训练数据，
# 重点用于在演示和真实写回之前提供更直观的安全提示。

SIGNATURE_PATTERN = re.compile(
    r"^\s*(def|class|async def|function|interface|type)\s+",
    re.MULTILINE,
)
IMPORT_PATTERN = re.compile(r"^\s*(import|from)\s+", re.MULTILINE)
CODE_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".jsx", ".json", ".yaml", ".yml", ".toml"}


@dataclass
class ActionRiskAssessment:
    target_file: str
    score: int
    level: str
    reason: str


@dataclass
class ActionRiskSummary:
    overall_score: int = 0
    overall_level: str = "low"
    overall_reason: str = ""
    assessments: list[ActionRiskAssessment] = field(default_factory=list)


class ActionRiskTool:
    """
    基于规则和工程特征对文件动作做风险评估。
    """

    def assess(
        self,
        actions: list[FileActionModel],
        context: AgentContextModel,
    ) -> ActionRiskSummary:
        if not actions:
            return ActionRiskSummary()

        directories = {
            str(Path(action.targetFile).resolve().parent).lower()
            for action in actions
        }
        assessments: list[ActionRiskAssessment] = []

        for action in actions:
            score, reasons = self._score_action(
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
                )
            )

        overall_score = min(
            100,
            max(assessment.score for assessment in assessments)
            + max(0, len(actions) - 1) * 6
            + max(0, len(directories) - 1) * 4,
        )
        overall_level = self._level_from_score(overall_score)
        overall_reason = self._build_overall_reason(actions, assessments, len(directories))

        return ActionRiskSummary(
            overall_score=overall_score,
            overall_level=overall_level,
            overall_reason=overall_reason,
            assessments=assessments,
        )

    def _score_action(
        self,
        action: FileActionModel,
        context: AgentContextModel,
        action_count: int,
        directory_count: int,
    ) -> tuple[int, list[str]]:
        score = 0
        reasons: list[str] = []
        target_path = Path(action.targetFile)
        suffix = target_path.suffix.lower()
        original_content = action.originalContent or ""
        updated_content = action.updatedContent or ""

        if action.kind == "create_file":
            score += 18
            reasons.append("包含新增文件")
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

        if directory_count > 1:
            score += 8
            reasons.append("修改跨越多个目录")

        if self._has_signature_change(original_content, updated_content):
            score += 20
            reasons.append("检测到函数或类型签名变化")

        if self._has_import_change(original_content, updated_content):
            score += 10
            reasons.append("检测到导入关系变化")

        if self._has_large_content_delta(original_content, updated_content):
            score += 12
            reasons.append("文件改动规模较大")

        active_file = (context.activeFile or "").strip().lower()
        if active_file and active_file != str(target_path).lower():
            score += 6
            reasons.append("目标文件不是当前活动文件")

        if action.kind == "update_documentation":
            score = max(0, score - 8)

        return min(100, score), reasons

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

        if not reasons:
            reasons.append("本次修改范围较集中")

        return "，".join(reasons[:3])
