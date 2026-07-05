from __future__ import annotations

import argparse
import csv
import json
import platform
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from backend.agent_workflow import AgentWorkflow
from backend.ml.attention_memory import AttentionMemoryTool
from backend.ml.context_candidate import ContextCandidateChunk, build_workspace_context_chunks
from backend.ml.embedding_provider import build_embedding_provider_from_env, normalize_matrix
from backend.models import AgentContextModel


VARIANT_EMBEDDING_ONLY = "embedding_only"
VARIANT_ATTENTION = "embedding_attention"
VARIANT_ATTENTION_CALL_CHAIN = "embedding_attention_call_chain"
VARIANT_ATTENTION_CALL_CHAIN_MEMORY = "embedding_attention_call_chain_memory"
VARIANT_LABELS = {
    VARIANT_EMBEDDING_ONLY: "仅 Embedding",
    VARIANT_ATTENTION: "Embedding + 多头注意力",
    VARIANT_ATTENTION_CALL_CHAIN: "Embedding + 多头注意力 + 调用链",
    VARIANT_ATTENTION_CALL_CHAIN_MEMORY: "Embedding + 多头注意力 + 调用链 + 记忆",
}
VARIANT_SHORT_LABELS = {
    VARIANT_EMBEDDING_ONLY: "仅 Embedding",
    VARIANT_ATTENTION: "Embedding + 多头注意力",
    VARIANT_ATTENTION_CALL_CHAIN: "Embedding + 多头注意力 + 调用链",
    VARIANT_ATTENTION_CALL_CHAIN_MEMORY: "Embedding + 多头注意力 + 调用链 + 记忆",
}
CASE_GROUP_ORDER = [
    "report_generation",
    "json_loading",
    "json_saving",
    "average_score",
    "student_creation",
    "score_validation",
    "record_serialization",
    "demo_entry",
]

GLOBAL_MEMORY_ITEMS = [
    "项目记忆：StudentScoreManager 位于 manager.py，负责学生成绩管理、加载保存、统计和报表生成调度。",
    "项目记忆：StudentStorage 位于 storage.py，负责 JSON 文件读取和写回。",
    "项目记忆：StudentRecord 位于 models.py，负责学生成绩实体、平均分计算、字典转换和成绩范围校验。",
    "项目记忆：演示入口一般位于 main.py 的 run_demo 或 build_demo_manager。",
]


@dataclass(frozen=True)
class ExpectedTarget:
    path: str
    symbols: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ExperimentCase:
    case_id: str
    case_label: str
    prompt: str
    expected_targets: list[ExpectedTarget]
    memory_items: list[str] = field(default_factory=list)


@dataclass
class FlatMatch:
    case_id: str
    variant: str
    rank: int
    source: str
    title: str
    identifier: str
    chunk_type: str
    location: str
    score: float
    attention_weight: float
    cosine_similarity: float
    retrieval_score: float
    head_weights: list[float]
    excerpt: str
    embedding_provider: str = ""
    embedding_model: str = ""
    fallback_used: bool = False
    warning: str = ""
    expected_hit: bool = False


@dataclass
class VariantEvaluation:
    case_id: str
    case_label: str
    prompt: str
    variant: str
    expected_targets: list[dict[str, Any]]
    expected_rank_any: int | None
    expected_rank_workspace: int | None
    hit_at_1_any: bool
    hit_at_3_any: bool
    hit_at_1_workspace: bool
    hit_at_3_workspace: bool
    reciprocal_rank_any: float
    reciprocal_rank_workspace: float
    top_title: str
    top_source: str
    top_score: float


def build_default_cases() -> list[ExperimentCase]:
    groups = [
        (
            "report_generation",
            "报表生成",
            [
                "报表生成逻辑在哪里？",
                "成绩报告文本是由哪个方法生成的？",
                "如果我要修改报告输出流程，应该先看哪个函数？",
                "生成完整成绩报告的入口方法是什么？",
                "报表生成时 manager 和 report 的协作代码在哪里？",
                "帮我定位 build_full_report 被哪个业务方法调用。",
            ],
            [
                ExpectedTarget("manager.py", ["StudentScoreManager.generate_report", "generate_report"]),
                ExpectedTarget("report.py", ["build_full_report", "run_demo"]),
            ],
            "本轮任务记忆：报表生成调度入口通常是 manager.py 中的 StudentScoreManager.generate_report。",
        ),
        (
            "json_loading",
            "JSON读取",
            [
                "学生成绩 JSON 文件是在哪里读取并转换成对象的？",
                "读取 sample_data.json 的底层实现在哪？",
                "load_students 最终调用了哪个存储层方法？",
                "JSON 数据加载后是在哪里变成 StudentRecord 的？",
                "从文件读取学生成绩列表的代码位置在哪里？",
                "帮我找一下 StudentStorage.load 和 from_dict 相关逻辑。",
                "如果数据文件不存在，读取流程会走到哪里？",
            ],
            [
                ExpectedTarget("storage.py", ["StudentStorage.load", "load"]),
                ExpectedTarget("models.py", ["StudentRecord.from_dict", "from_dict"]),
            ],
            "本轮任务记忆：JSON 读取在 storage.py 的 StudentStorage.load，字典转对象在 models.py 的 StudentRecord.from_dict。",
        ),
        (
            "json_saving",
            "JSON保存",
            [
                "保存学生成绩到 JSON 文件的逻辑在哪里？",
                "save_students 最终调用了哪个底层写文件方法？",
                "学生成绩列表写回文件时会经过哪些函数？",
                "json.dump 是在哪个方法里调用的？",
                "保存前把 StudentRecord 转成字典的代码在哪里？",
                "我想修改成绩保存格式，应该看哪个方法？",
                "序列化后写入 JSON 的调用链在哪里？",
            ],
            [
                ExpectedTarget("storage.py", ["StudentStorage.save", "save"]),
                ExpectedTarget("models.py", ["StudentRecord.to_dict", "to_dict"]),
            ],
            "本轮任务记忆：JSON 写回在 storage.py 的 StudentStorage.save，序列化在 models.py 的 StudentRecord.to_dict。",
        ),
        (
            "average_score",
            "平均分计算",
            [
                "平均分是如何计算的？",
                "全班平均分的计算逻辑在哪个方法？",
                "单个学生平均分和全班平均分分别在哪里实现？",
                "average_score 是在哪里被调用的？",
                "如果我要优化平均分统计，应该看哪些方法？",
                "avg 属性背后调用的平均分方法在哪里？",
            ],
            [
                ExpectedTarget("manager.py", ["StudentScoreManager.calculate_average_score", "calculate_average_score"]),
                ExpectedTarget("models.py", ["StudentRecord.average_score", "average_score", "avg"]),
            ],
            "本轮任务记忆：单个学生平均分在 StudentRecord.average_score，全班平均分在 StudentScoreManager.calculate_average_score。",
        ),
        (
            "student_creation",
            "新增学生",
            [
                "新增学生记录的入口方法在哪里？",
                "单个学生成绩记录是在哪个方法里 append 的？",
                "批量新增学生记录的逻辑在哪里？",
                "StudentRecord 构造是在 manager 的哪个方法中发生的？",
                "添加硬编码演示学生时会调用哪个业务方法？",
                "add_student 和 add_students 的代码位置在哪里？",
            ],
            [
                ExpectedTarget("manager.py", ["StudentScoreManager.add_student", "add_student"]),
                ExpectedTarget("manager.py", ["StudentScoreManager.add_students", "add_students"]),
            ],
            "本轮任务记忆：新增单个学生记录使用 StudentScoreManager.add_student，批量新增使用 add_students。",
        ),
        (
            "score_validation",
            "成绩校验",
            [
                "成绩范围校验在哪里完成？",
                "0 到 100 的成绩限制在哪段代码里？",
                "StudentRecord 初始化后如何处理非法成绩？",
                "如果成绩超过 100，会在哪里被重置？",
                "__post_init__ 方法负责什么校验？",
                "数学英语 Python 成绩的有效范围在哪里判断？",
            ],
            [
                ExpectedTarget("models.py", ["StudentRecord.__post_init__", "__post_init__"]),
            ],
            "本轮任务记忆：成绩范围校验在 StudentRecord.__post_init__，超出 0 到 100 的成绩会被重置。",
        ),
        (
            "record_serialization",
            "字典序列化",
            [
                "学生记录如何转换成字典以便保存？",
                "to_dict 方法在哪里定义？",
                "保存前 name/math/english/python 字段是在哪里组装的？",
                "StudentRecord 序列化为 dict 的逻辑在哪？",
                "serialized 列表里的字典来自哪个方法？",
                "写 JSON 前的对象转字典代码在哪里？",
            ],
            [
                ExpectedTarget("models.py", ["StudentRecord.to_dict", "to_dict"]),
            ],
            "本轮任务记忆：学生记录保存前通过 StudentRecord.to_dict 转成可序列化字典。",
        ),
        (
            "demo_entry",
            "演示入口",
            [
                "演示程序的运行入口在哪里？",
                "run_demo 函数在哪个文件里？",
                "构造演示 manager 的函数是什么？",
                "程序启动后如何生成并打印报告？",
                "if __name__ == '__main__' 下面调用了什么？",
                "示例项目的主流程入口代码在哪里？",
            ],
            [
                ExpectedTarget("main.py", ["run_demo", "build_demo_manager"]),
                ExpectedTarget("report.py", ["run_demo", "build_demo_manager"]),
            ],
            "本轮任务记忆：演示流程入口通常是 main.py 的 run_demo，辅助构造函数是 build_demo_manager。",
        ),
    ]
    cases: list[ExperimentCase] = []
    for group_id, group_label, prompts, targets, memory_item in groups:
        for index, prompt in enumerate(prompts, start=1):
            cases.append(
                ExperimentCase(
                    case_id=f"{group_id}_{index:02d}",
                    case_label=f"{group_label}{index:02d}",
                    prompt=prompt,
                    expected_targets=targets,
                    memory_items=[memory_item],
                )
            )

    return cases


def run_experiment(
    *,
    workspace_root: Path,
    output_root: Path,
    top_k: int,
) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = output_root / timestamp
    charts_dir = run_dir / "charts"
    charts_dir.mkdir(parents=True, exist_ok=True)

    workflow = AgentWorkflow()
    active_file = workspace_root / "manager.py"
    context = AgentContextModel(
        workspaceRoot=str(workspace_root),
        activeFile=str(active_file if active_file.exists() else workspace_root),
        languageId="python",
    )

    cases = build_default_cases()
    flat_matches: list[FlatMatch] = []
    evaluations: list[VariantEvaluation] = []
    raw_cases: list[dict[str, Any]] = []

    for case in cases:
        search_result = workflow.inspect_workspace(context, case.prompt)
        semantic_result = workflow.inspect_workspace_semantics(context, case.prompt, search_result)
        workspace_chunks = build_workspace_context_chunks(
            search_result,
            semantic_result,
            enable_call_chain=False,
        )

        variant_matches: dict[str, list[FlatMatch]] = {}
        variant_matches[VARIANT_EMBEDDING_ONLY] = rank_embedding_only(
            context=context,
            prompt=case.prompt,
            chunks=workspace_chunks,
            top_k=top_k,
            case_id=case.case_id,
        )
        variant_matches[VARIANT_ATTENTION] = rank_with_attention(
            context=context,
            prompt=case.prompt,
            search_result=search_result,
            semantic_result=semantic_result,
            memory_items=[],
            top_k=top_k,
            case_id=case.case_id,
            variant=VARIANT_ATTENTION,
            enable_call_chain=False,
        )
        variant_matches[VARIANT_ATTENTION_CALL_CHAIN] = rank_with_attention(
            context=context,
            prompt=case.prompt,
            search_result=search_result,
            semantic_result=semantic_result,
            memory_items=[],
            top_k=top_k,
            case_id=case.case_id,
            variant=VARIANT_ATTENTION_CALL_CHAIN,
            enable_call_chain=True,
        )
        variant_matches[VARIANT_ATTENTION_CALL_CHAIN_MEMORY] = rank_with_attention(
            context=context,
            prompt=case.prompt,
            search_result=search_result,
            semantic_result=semantic_result,
            memory_items=[*GLOBAL_MEMORY_ITEMS, *case.memory_items],
            top_k=top_k,
            case_id=case.case_id,
            variant=VARIANT_ATTENTION_CALL_CHAIN_MEMORY,
            enable_call_chain=True,
        )

        case_record = {
            "caseId": case.case_id,
            "caseLabel": case.case_label,
            "prompt": case.prompt,
            "expectedTargets": [asdict(target) for target in case.expected_targets],
            "semanticMetadata": {
                "queryTerms": semantic_result.query_terms,
                "embeddingProvider": semantic_result.embedding_provider,
                "embeddingModel": semantic_result.embedding_model,
                "fallbackUsed": semantic_result.fallback_used,
                "warning": semantic_result.warning,
            },
            "semanticMatches": [asdict(match) for match in semantic_result.matches],
            "variants": {},
        }

        for variant, matches in variant_matches.items():
            for match in matches:
                match.expected_hit = is_expected_hit(match, case.expected_targets)
            evaluation = evaluate_variant(case, variant, matches)
            evaluations.append(evaluation)
            flat_matches.extend(matches)
            case_record["variants"][variant] = {
                "evaluation": asdict(evaluation),
                "matches": [asdict(match) for match in matches],
            }

        raw_cases.append(case_record)

    aggregate_rows = build_aggregate_rows(evaluations, len(cases))
    font_name = render_charts(evaluations, aggregate_rows, charts_dir)

    metadata = {
        "experimentName": "Embedding 与多头注意力上下文选择消融实验",
        "timestamp": timestamp,
        "workspaceRoot": str(workspace_root),
        "outputDirectory": str(run_dir),
        "topK": top_k,
        "pythonVersion": platform.python_version(),
        "platform": platform.platform(),
        "gitCommit": get_git_commit(),
        "gitStatusShort": get_git_status_short(),
        "fontName": font_name,
        "variants": VARIANT_LABELS,
    }
    raw_result = {
        "metadata": metadata,
        "aggregate": aggregate_rows,
        "cases": raw_cases,
    }

    write_json(run_dir / "results.json", raw_result)
    write_matches_csv(run_dir / "matches.csv", flat_matches)
    write_summary_csv(run_dir / "summary.csv", evaluations)
    write_aggregate_csv(run_dir / "aggregate.csv", aggregate_rows)
    write_markdown_report(run_dir / "实验报告.md", metadata, aggregate_rows, evaluations)

    return run_dir


def rank_embedding_only(
    *,
    context: AgentContextModel,
    prompt: str,
    chunks: list[ContextCandidateChunk],
    top_k: int,
    case_id: str,
) -> list[FlatMatch]:
    if not chunks:
        return []

    query_text = build_query_text(context, prompt)
    embedding_provider = build_embedding_provider_from_env()
    embedding_result = embedding_provider.embed_texts([query_text] + [chunk.content for chunk in chunks])
    matrix = normalize_matrix(embedding_result.vectors)
    if matrix.ndim != 2 or matrix.shape[0] != len(chunks) + 1:
        return []

    query_vector = matrix[0]
    chunk_vectors = matrix[1:]
    scores = np.clip((chunk_vectors @ query_vector + 1.0) / 2.0, 0.0, 1.0)
    ranked = sorted(enumerate(scores), key=lambda item: float(item[1]), reverse=True)

    matches: list[FlatMatch] = []
    for rank, (index, score) in enumerate(ranked[:top_k], start=1):
        chunk = chunks[index]
        matches.append(
            FlatMatch(
                case_id=case_id,
                variant=VARIANT_EMBEDDING_ONLY,
                rank=rank,
                source="workspace",
                title=chunk.title,
                identifier=chunk.identifier,
                chunk_type=chunk.chunk_type,
                location=chunk.location,
                score=float(score),
                attention_weight=0.0,
                cosine_similarity=float(score),
                retrieval_score=float(chunk.retrieval_score),
                head_weights=[],
                excerpt=truncate_for_record(chunk.content),
                embedding_provider=embedding_result.provider_name,
                embedding_model=embedding_result.model_name,
                fallback_used=embedding_result.fallback_used,
                warning=embedding_result.warning,
            )
        )
    return matches


def rank_with_attention(
    *,
    context: AgentContextModel,
    prompt: str,
    search_result,
    semantic_result,
    memory_items: list[str],
    top_k: int,
    case_id: str,
    variant: str,
    enable_call_chain: bool,
) -> list[FlatMatch]:
    tool = AttentionMemoryTool(top_k=top_k, enable_call_chain=enable_call_chain)
    result = tool.select(
        context=context,
        prompt=prompt,
        search_result=search_result,
        semantic_result=semantic_result,
        conversation_history=[],
        memory_items=memory_items,
    )

    matches: list[FlatMatch] = []
    for rank, match in enumerate(result.matches, start=1):
        matches.append(
            FlatMatch(
                case_id=case_id,
                variant=variant,
                rank=rank,
                source=match.source,
                title=match.title,
                identifier=match.identifier,
                chunk_type=match.chunk_type,
                location=match.location,
                score=float(match.weight),
                attention_weight=float(match.attention_weight),
                cosine_similarity=float(match.cosine_similarity),
                retrieval_score=float(match.retrieval_score),
                head_weights=match.head_weights,
                excerpt=truncate_for_record(match.excerpt),
                embedding_provider=result.embedding_provider,
                embedding_model=result.embedding_model,
                fallback_used=result.fallback_used,
                warning=result.warning,
            )
        )
    return matches


def evaluate_variant(
    case: ExperimentCase,
    variant: str,
    matches: list[FlatMatch],
) -> VariantEvaluation:
    any_rank = find_first_rank(matches, case.expected_targets, workspace_only=False)
    workspace_rank = find_first_rank(matches, case.expected_targets, workspace_only=True)
    top_match = matches[0] if matches else None
    return VariantEvaluation(
        case_id=case.case_id,
        case_label=case.case_label,
        prompt=case.prompt,
        variant=variant,
        expected_targets=[asdict(target) for target in case.expected_targets],
        expected_rank_any=any_rank,
        expected_rank_workspace=workspace_rank,
        hit_at_1_any=any_rank == 1,
        hit_at_3_any=any_rank is not None and any_rank <= 3,
        hit_at_1_workspace=workspace_rank == 1,
        hit_at_3_workspace=workspace_rank is not None and workspace_rank <= 3,
        reciprocal_rank_any=1.0 / any_rank if any_rank else 0.0,
        reciprocal_rank_workspace=1.0 / workspace_rank if workspace_rank else 0.0,
        top_title=top_match.title if top_match else "",
        top_source=top_match.source if top_match else "",
        top_score=top_match.score if top_match else 0.0,
    )


def is_expected_hit(match: FlatMatch, targets: list[ExpectedTarget]) -> bool:
    return any(match_satisfies_target(match, target) for target in targets)


def find_first_rank(
    matches: list[FlatMatch],
    targets: list[ExpectedTarget],
    *,
    workspace_only: bool,
) -> int | None:
    for match in matches:
        if workspace_only and match.source != "workspace":
            continue
        if is_expected_hit(match, targets):
            return match.rank
    return None


def match_satisfies_target(match: FlatMatch, target: ExpectedTarget) -> bool:
    haystack = normalize_text(
        " ".join(
            [
                match.source,
                match.title,
                match.identifier,
                match.chunk_type,
                match.location,
                match.excerpt,
            ]
        )
    )
    target_path = normalize_text(target.path)
    if target_path and target_path not in haystack:
        return False

    if not target.symbols:
        return True

    for symbol in target.symbols:
        normalized_symbol = normalize_text(symbol)
        symbol_variants = {
            normalized_symbol,
            normalized_symbol.replace(".", "::"),
            normalized_symbol.replace("::", "."),
        }
        if "." in normalized_symbol:
            symbol_variants.add(normalized_symbol.split(".")[-1])
        if "::" in normalized_symbol:
            symbol_variants.add(normalized_symbol.split("::")[-1])
        if any(variant and variant in haystack for variant in symbol_variants):
            return True
    return False


def build_aggregate_rows(
    evaluations: list[VariantEvaluation],
    case_count: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for variant in VARIANT_LABELS:
        variant_evaluations = [item for item in evaluations if item.variant == variant]
        if not variant_evaluations:
            continue
        rows.append(
            {
                "variant": variant,
                "variantLabel": VARIANT_LABELS[variant],
                "caseCount": case_count,
                "hitAt1Any": mean_bool(item.hit_at_1_any for item in variant_evaluations),
                "hitAt3Any": mean_bool(item.hit_at_3_any for item in variant_evaluations),
                "hitAt1Workspace": mean_bool(item.hit_at_1_workspace for item in variant_evaluations),
                "hitAt3Workspace": mean_bool(item.hit_at_3_workspace for item in variant_evaluations),
                "mrrAny": mean(item.reciprocal_rank_any for item in variant_evaluations),
                "mrrWorkspace": mean(item.reciprocal_rank_workspace for item in variant_evaluations),
            }
        )
    return rows


def render_charts(
    evaluations: list[VariantEvaluation],
    aggregate_rows: list[dict[str, Any]],
    charts_dir: Path,
) -> str:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib import font_manager
    except Exception as exc:
        (charts_dir / "CHARTS_SKIPPED.txt").write_text(
            f"matplotlib 不可用，图表未生成：{exc}",
            encoding="utf-8",
        )
        return ""

    available_fonts = {font.name for font in font_manager.fontManager.ttflist}
    preferred_fonts = [
        "Microsoft YaHei",
        "SimHei",
        "DengXian",
        "Noto Sans CJK SC",
        "Source Han Sans SC",
        "PingFang SC",
    ]
    selected_font = next((font for font in preferred_fonts if font in available_fonts), "DejaVu Sans")
    plt.rcParams["font.sans-serif"] = [selected_font, *preferred_fonts, "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    plt.rcParams["svg.fonttype"] = "none"

    plot_aggregate_metrics(plt, aggregate_rows, charts_dir)
    plot_overall_metrics(plt, aggregate_rows, charts_dir)
    plot_workspace_metrics(plt, aggregate_rows, charts_dir)
    plot_rank_heatmap(plt, evaluations, charts_dir)
    return selected_font


def plot_aggregate_metrics(plt, aggregate_rows: list[dict[str, Any]], charts_dir: Path) -> None:
    metrics = [
        ("hitAt1Any", "Hit@1"),
        ("hitAt3Any", "Hit@3"),
        ("mrrAny", "MRR"),
        ("hitAt3Workspace", "Workspace Hit@3"),
    ]
    labels = [row["variantLabel"] for row in aggregate_rows]
    x = np.arange(len(labels))
    width = 0.18

    fig, ax = plt.subplots(figsize=(11, 5.8))
    for index, (metric_key, metric_label) in enumerate(metrics):
        values = [float(row[metric_key]) for row in aggregate_rows]
        positions = x + (index - 1.5) * width
        bars = ax.bar(positions, values, width, label=metric_label)
        for bar, value in zip(bars, values):
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() + 0.015,
                f"{value:.2f}",
                ha="center",
                va="bottom",
                fontsize=9,
            )

    ax.set_title("上下文选择消融实验总体指标")
    ax.set_ylabel("指标值")
    ax.set_ylim(0, 1.12)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=10, ha="right")
    ax.legend(loc="lower right")
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    save_figure(fig, charts_dir / "aggregate_metrics")
    plt.close(fig)


def plot_overall_metrics(plt, aggregate_rows: list[dict[str, Any]], charts_dir: Path) -> None:
    metrics = [
        ("hitAt1Any", "Hit@1"),
        ("hitAt3Any", "Hit@3"),
        ("mrrAny", "MRR"),
    ]
    plot_metric_group(
        plt,
        aggregate_rows,
        metrics,
        "综合上下文命中指标",
        charts_dir / "overall_context_metrics",
    )


def plot_workspace_metrics(plt, aggregate_rows: list[dict[str, Any]], charts_dir: Path) -> None:
    metrics = [
        ("hitAt1Workspace", "Workspace Hit@1"),
        ("hitAt3Workspace", "Workspace Hit@3"),
        ("mrrWorkspace", "Workspace MRR"),
    ]
    plot_metric_group(
        plt,
        aggregate_rows,
        metrics,
        "代码片段定位指标",
        charts_dir / "workspace_context_metrics",
    )


def plot_metric_group(
    plt,
    aggregate_rows: list[dict[str, Any]],
    metrics: list[tuple[str, str]],
    title: str,
    output_path: Path,
) -> None:
    labels = [row["variantLabel"] for row in aggregate_rows]
    x = np.arange(len(labels))
    width = 0.22

    fig, ax = plt.subplots(figsize=(11, 5.8))
    offset_base = (len(metrics) - 1) / 2
    for index, (metric_key, metric_label) in enumerate(metrics):
        values = [float(row[metric_key]) for row in aggregate_rows]
        positions = x + (index - offset_base) * width
        bars = ax.bar(positions, values, width, label=metric_label)
        for bar, value in zip(bars, values):
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() + 0.015,
                f"{value:.2f}",
                ha="center",
                va="bottom",
                fontsize=9,
            )

    ax.set_title(title)
    ax.set_ylabel("指标值")
    ax.set_ylim(0, 1.12)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=10, ha="right")
    ax.legend(loc="lower right")
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    save_figure(fig, output_path)
    plt.close(fig)


def plot_rank_heatmap(plt, evaluations: list[VariantEvaluation], charts_dir: Path) -> None:
    selected_case_ids = select_representative_case_ids(evaluations, max_cases=8)
    case_ids = selected_case_ids or list(dict.fromkeys(item.case_id for item in evaluations))
    case_labels = [
        display_case_group_label(
            next((item.case_label for item in evaluations if item.case_id == case_id), case_id)
        )
        for case_id in case_ids
    ]
    variants = list(VARIANT_LABELS.keys())
    matrix = np.zeros((len(case_ids), len(variants)), dtype=np.float64)
    annotations: list[list[str]] = [["" for _ in variants] for _ in case_ids]
    by_key = {(item.case_id, item.variant): item for item in evaluations}

    for row_index, case_id in enumerate(case_ids):
        for col_index, variant in enumerate(variants):
            item = by_key.get((case_id, variant))
            if not item:
                annotations[row_index][col_index] = "-"
                continue
            matrix[row_index, col_index] = item.reciprocal_rank_any
            annotations[row_index][col_index] = (
                f"R{item.expected_rank_any}" if item.expected_rank_any else "未命中"
            )

    write_representative_case_csv(charts_dir / "rank_heatmap_cases.csv", case_ids, evaluations)

    fig, ax = plt.subplots(figsize=(7.4, 9.0))
    image = ax.imshow(matrix, cmap="YlGnBu", vmin=0, vmax=1, aspect="equal")
    ax.set_title("各样例期望上下文命中排名（颜色为 Reciprocal Rank）", fontsize=15)
    ax.set_xticks(np.arange(len(variants)))
    ax.set_xticklabels(
        [VARIANT_SHORT_LABELS[variant] for variant in variants],
        rotation=16,
        ha="right",
        rotation_mode="anchor",
    )
    ax.set_yticks(np.arange(len(case_ids)))
    ax.set_yticklabels(case_labels)

    for row_index in range(len(case_ids)):
        for col_index in range(len(variants)):
            value = matrix[row_index, col_index]
            text_color = "white" if value > 0.55 else "black"
            ax.text(
                col_index,
                row_index,
                annotations[row_index][col_index],
                ha="center",
                va="center",
                color=text_color,
                fontsize=11,
            )

    fig.colorbar(image, ax=ax, fraction=0.046, pad=0.04)
    fig.tight_layout()
    save_figure(fig, charts_dir / "rank_heatmap")
    plt.close(fig)


def select_representative_case_ids(
    evaluations: list[VariantEvaluation],
    *,
    max_cases: int,
) -> list[str]:
    case_ids = list(dict.fromkeys(item.case_id for item in evaluations))
    by_key = {(item.case_id, item.variant): item for item in evaluations}

    def improvement(case_id: str) -> float:
        base = by_key.get((case_id, VARIANT_EMBEDDING_ONLY))
        final = by_key.get((case_id, VARIANT_ATTENTION_CALL_CHAIN_MEMORY))
        if not base or not final:
            return 0.0
        return final.reciprocal_rank_any - base.reciprocal_rank_any

    selected: list[str] = []
    for group_id in CASE_GROUP_ORDER:
        group_case_ids = [case_id for case_id in case_ids if item_group_id(case_id) == group_id]
        if not group_case_ids:
            continue
        selected.append(
            min(
                group_case_ids,
                key=lambda item: (
                    -improvement(item),
                    by_key.get((item, VARIANT_ATTENTION_CALL_CHAIN_MEMORY)).expected_rank_any
                    if by_key.get((item, VARIANT_ATTENTION_CALL_CHAIN_MEMORY))
                    and by_key.get((item, VARIANT_ATTENTION_CALL_CHAIN_MEMORY)).expected_rank_any
                    else 999,
                    item,
                ),
            )
        )
        if len(selected) >= max_cases:
            return selected

    return selected


def item_group_id(case_id: str) -> str:
    return case_id.rsplit("_", 1)[0]


def display_case_group_label(case_label: str) -> str:
    return case_label.rstrip("0123456789")


def write_representative_case_csv(
    path: Path,
    case_ids: list[str],
    evaluations: list[VariantEvaluation],
) -> None:
    by_key = {(item.case_id, item.variant): item for item in evaluations}
    fieldnames = [
        "case_id",
        "case_label",
        "prompt",
        "embedding_only_rank",
        "final_rank",
        "reciprocal_rank_improvement",
        "selection_reason",
    ]
    rows: list[dict[str, Any]] = []
    for case_id in case_ids:
        base = by_key.get((case_id, VARIANT_EMBEDDING_ONLY))
        final = by_key.get((case_id, VARIANT_ATTENTION_CALL_CHAIN_MEMORY))
        if not final:
            continue
        base_rr = base.reciprocal_rank_any if base else 0.0
        improvement = final.reciprocal_rank_any - base_rr
        reason = "覆盖任务类型"
        if improvement > 0:
            reason = "最终方案提升明显"
        if final.expected_rank_any is None:
            reason = "最终方案仍未命中，用于分析边界"
        rows.append(
            {
                "case_id": case_id,
                "case_label": final.case_label,
                "prompt": final.prompt,
                "embedding_only_rank": base.expected_rank_any if base and base.expected_rank_any else "未命中",
                "final_rank": final.expected_rank_any if final.expected_rank_any else "未命中",
                "reciprocal_rank_improvement": f"{improvement:.3f}",
                "selection_reason": reason,
            }
        )

    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def save_figure(fig, path_without_suffix: Path) -> None:
    fig.savefig(path_without_suffix.with_suffix(".png"), dpi=180, bbox_inches="tight")
    fig.savefig(path_without_suffix.with_suffix(".svg"), bbox_inches="tight")


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def write_matches_csv(path: Path, matches: list[FlatMatch]) -> None:
    fieldnames = [
        "case_id",
        "variant",
        "rank",
        "source",
        "title",
        "identifier",
        "chunk_type",
        "location",
        "score",
        "attention_weight",
        "cosine_similarity",
        "retrieval_score",
        "head_weights",
        "embedding_provider",
        "embedding_model",
        "fallback_used",
        "warning",
        "expected_hit",
        "excerpt",
    ]
    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for match in matches:
            row = asdict(match)
            row["head_weights"] = json.dumps(match.head_weights, ensure_ascii=False)
            writer.writerow(row)


def write_summary_csv(path: Path, evaluations: list[VariantEvaluation]) -> None:
    fieldnames = [
        "case_id",
        "case_label",
        "prompt",
        "variant",
        "expected_targets",
        "expected_rank_any",
        "expected_rank_workspace",
        "hit_at_1_any",
        "hit_at_3_any",
        "hit_at_1_workspace",
        "hit_at_3_workspace",
        "reciprocal_rank_any",
        "reciprocal_rank_workspace",
        "top_title",
        "top_source",
        "top_score",
    ]
    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for evaluation in evaluations:
            row = asdict(evaluation)
            row["expected_targets"] = json.dumps(evaluation.expected_targets, ensure_ascii=False)
            writer.writerow(row)


def write_aggregate_csv(path: Path, aggregate_rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "variant",
        "variantLabel",
        "caseCount",
        "hitAt1Any",
        "hitAt3Any",
        "hitAt1Workspace",
        "hitAt3Workspace",
        "mrrAny",
        "mrrWorkspace",
    ]
    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(aggregate_rows)


def write_markdown_report(
    path: Path,
    metadata: dict[str, Any],
    aggregate_rows: list[dict[str, Any]],
    evaluations: list[VariantEvaluation],
) -> None:
    lines = [
        "# Embedding 与多头注意力上下文选择消融实验报告",
        "",
        f"- 实验时间：{metadata['timestamp']}",
        f"- 工作区：`{metadata['workspaceRoot']}`",
        f"- Top K：{metadata['topK']}",
        f"- Python 版本：{metadata['pythonVersion']}",
        f"- 运行平台：{metadata['platform']}",
        f"- Git Commit：`{metadata.get('gitCommit') or 'unknown'}`",
        f"- 图表中文字体：{metadata.get('fontName') or '未生成图表'}",
        "",
        "## 输出文件",
        "",
        "- `results.json`：完整原始结果，适合后续二次分析。",
        "- `matches.csv`：逐候选片段明细，使用 UTF-8 BOM，方便 Excel 打开中文。",
        "- `summary.csv`：逐样例、逐方案命中指标。",
        "- `aggregate.csv`：整体汇总指标。",
        "- `charts/aggregate_metrics.png` / `.svg`：整体指标图。",
        "- `charts/overall_context_metrics.png` / `.svg`：综合上下文命中指标图。",
        "- `charts/workspace_context_metrics.png` / `.svg`：代码片段定位指标图。",
        "- `charts/rank_heatmap.png` / `.svg`：8 类任务代表样例命中排名热力图，避免 50 条样例全部堆叠导致不可读。",
        "- `charts/rank_heatmap_cases.csv`：热力图所选代表性样例及选择原因。",
        "",
        "## 汇总指标",
        "",
        "| 方案 | 样例数 | Hit@1 | Hit@3 | Workspace Hit@1 | Workspace Hit@3 | MRR | Workspace MRR |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in aggregate_rows:
        lines.append(
            "| {label} | {count} | {hit1:.3f} | {hit3:.3f} | {whit1:.3f} | {whit3:.3f} | {mrr:.3f} | {wmrr:.3f} |".format(
                label=row["variantLabel"],
                count=row["caseCount"],
                hit1=float(row["hitAt1Any"]),
                hit3=float(row["hitAt3Any"]),
                whit1=float(row["hitAt1Workspace"]),
                whit3=float(row["hitAt3Workspace"]),
                mrr=float(row["mrrAny"]),
                wmrr=float(row["mrrWorkspace"]),
            )
        )

    lines.extend(
        [
            "",
            "## 图表",
            "",
            "![整体指标](charts/aggregate_metrics.png)",
            "",
            "![综合上下文命中指标](charts/overall_context_metrics.png)",
            "",
            "![代码片段定位指标](charts/workspace_context_metrics.png)",
            "",
            "![命中排名热力图](charts/rank_heatmap.png)",
            "",
            "热力图展示 8 类任务各 1 个代表样例。选择规则是：按任务类型覆盖报表生成、JSON 读取、JSON 保存、平均分计算、新增学生、成绩校验、字典序列化和演示入口，并在每类任务中选择最终方案相比仅 Embedding 提升较明显的样例。50 条全量结果仍保存在 `summary.csv` 和 `matches.csv` 中。",
            "",
            "## 主实验图表解读",
            "",
            "- `aggregate_metrics` 用于总览四种消融方案的整体变化，横轴是方案，纵轴是 0 到 1 之间的指标值，越高表示上下文选择越准确。",
            "- `overall_context_metrics` 关注综合上下文命中能力，记忆片段和代码片段都可以算作命中，适合说明系统能否找到“有用信息”。",
            "- `workspace_context_metrics` 只统计工作区代码片段命中，适合说明系统是否真正定位到了代码文件、类或函数。",
            "- `rank_heatmap` 展示 8 类任务代表样例中期望上下文的排名变化，颜色越深表示 Reciprocal Rank 越高，即正确上下文越靠前；单元格中的 `R1`、`R2` 表示命中排名，`未命中` 表示 Top K 中没有找到期望上下文。",
            "",
            "## 逐样例结果",
            "",
            "| 样例 | 方案 | 期望排名 | 工作区期望排名 | Top 1 来源 | Top 1 标题 | Top 1 分数 |",
            "|---|---|---:|---:|---|---|---:|",
        ]
    )

    for evaluation in evaluations:
        lines.append(
            "| {case_id} | {variant} | {rank_any} | {rank_workspace} | {top_source} | {top_title} | {score:.3f} |".format(
                case_id=evaluation.case_label,
                variant=VARIANT_LABELS[evaluation.variant],
                rank_any=evaluation.expected_rank_any or "未命中",
                rank_workspace=evaluation.expected_rank_workspace or "未命中",
                top_source=evaluation.top_source,
                top_title=evaluation.top_title.replace("|", "\\|"),
                score=evaluation.top_score,
            )
        )

    lines.extend(
        [
            "",
            "## 指标说明",
            "",
            "- Hit@1 / Hit@3：期望上下文是否出现在前 1 / 前 3 个结果中，记忆片段和工作区片段都可计入。",
            "- Workspace Hit@1 / Workspace Hit@3：只统计工作区代码片段命中，便于观察是否真的定位到文件或方法。",
            "- MRR：期望上下文排名的倒数平均值，越接近 1 表示越靠前。",
            "- 本实验用于论文中的消融对比，重点观察 `Embedding only`、`Embedding + Attention`、`Embedding + Attention + Call Chain` 与 `Embedding + Attention + Call Chain + Memory` 的变化。",
            "",
        ]
    )

    path.write_text("\n".join(lines), encoding="utf-8")


def build_query_text(context: AgentContextModel, prompt: str) -> str:
    parts = [prompt]
    if context.selectedText:
        parts.append(context.selectedText)
    if context.activeFile:
        parts.append(context.activeFile)
    return "\n".join(part for part in parts if part)


def truncate_for_record(text: str, max_chars: int = 900) -> str:
    cleaned = text.strip()
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[:max_chars] + "\n...[truncated]"


def normalize_text(text: str) -> str:
    return text.replace("\\", "/").lower()


def get_git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return ""


def get_git_status_short() -> str:
    try:
        return subprocess.check_output(
            ["git", "status", "--short"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return ""


def mean_bool(values) -> float:
    bool_values = [1.0 if value else 0.0 for value in values]
    return mean(bool_values)


def mean(values) -> float:
    number_values = [float(value) for value in values]
    if not number_values:
        return 0.0
    return sum(number_values) / len(number_values)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="运行 Embedding 与多头注意力上下文选择消融实验，并把结果写入 log 目录。",
    )
    parser.add_argument(
        "--workspace",
        default="examples/student_score_project",
        help="用于评测的工作区目录，默认使用示例学生成绩项目。",
    )
    parser.add_argument(
        "--output-root",
        default="log/context_selection_experiments",
        help="实验结果输出根目录。",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=8,
        help="每种方案保留的 Top K 上下文数量。",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    workspace_root = Path(args.workspace).resolve()
    output_root = Path(args.output_root).resolve()
    if not workspace_root.exists() or not workspace_root.is_dir():
        raise SystemExit(f"工作区目录不存在：{workspace_root}")

    run_dir = run_experiment(
        workspace_root=workspace_root,
        output_root=output_root,
        top_k=max(1, args.top_k),
    )
    print(f"实验结果已写入：{run_dir}")


if __name__ == "__main__":
    main()
