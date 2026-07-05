"""Run a small reproducible benchmark for the local LoRA-ready coding model.

The script intentionally uses only the Python standard library so it can run in
the same lightweight environment as the FastAPI backend. It validates the eval
dataset, optionally calls Ollama for the base model and LoRA-ready model, then
writes JSON and Markdown evidence under the output directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib import request
from urllib.error import HTTPError, URLError


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_EVAL_FILE = PROJECT_ROOT / "data" / "lora" / "eval" / "coding_assistant_eval.jsonl"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "outputs" / "lora-benchmark"

REQUIRED_EVAL_FIELDS = {
    "id",
    "task_type",
    "instruction",
    "input",
    "expected_behavior",
    "scoring",
    "source",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate base vs LoRA-ready coding assistant behavior.")
    parser.add_argument("--eval-file", default=str(DEFAULT_EVAL_FILE), help="Path to eval JSONL file.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Directory for benchmark reports.")
    parser.add_argument("--base-model", default="qwen2.5-coder:7b", help="Ollama base model name.")
    parser.add_argument(
        "--candidate-model",
        default="yinlin-qwen-coding-agent",
        help="Ollama LoRA-ready model alias created from the Modelfile.",
    )
    parser.add_argument("--ollama-url", default="http://127.0.0.1:11434", help="Ollama base URL.")
    parser.add_argument("--timeout", type=int, default=180, help="Per-request timeout in seconds.")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of eval samples; 0 means all.")
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate dataset schema and skip Ollama calls.",
    )
    return parser.parse_args()


def resolve_path(path_text: str) -> Path:
    path = Path(path_text)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                value = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number} is not valid JSON: {exc}") from exc
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number} must be a JSON object")
            samples.append(value)
    return samples


def validate_eval_samples(samples: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    seen_ids: set[str] = set()

    for index, sample in enumerate(samples, start=1):
        sample_id = str(sample.get("id", f"row-{index}"))
        missing = sorted(REQUIRED_EVAL_FIELDS - set(sample))
        if missing:
            errors.append(f"{sample_id}: missing fields: {', '.join(missing)}")

        if sample_id in seen_ids:
            errors.append(f"{sample_id}: duplicate id")
        seen_ids.add(sample_id)

        scoring = sample.get("scoring")
        if not isinstance(scoring, dict):
            errors.append(f"{sample_id}: scoring must be an object")
            continue

        required_keywords = scoring.get("required_keywords", [])
        forbidden_keywords = scoring.get("forbidden_keywords", [])
        if not isinstance(required_keywords, list) or not all(isinstance(item, str) for item in required_keywords):
            errors.append(f"{sample_id}: scoring.required_keywords must be a string list")
        if not isinstance(forbidden_keywords, list) or not all(isinstance(item, str) for item in forbidden_keywords):
            errors.append(f"{sample_id}: scoring.forbidden_keywords must be a string list")

    return errors


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()
    except Exception:
        return "unknown"


def build_prompt(sample: dict[str, Any]) -> str:
    return "\n".join(
        [
            "请完成下面的编程助手任务，并用中文给出可以直接用于开发协作的回答。",
            "",
            "## 任务指令",
            str(sample["instruction"]).strip(),
            "",
            "## 输入上下文",
            str(sample["input"]).strip(),
            "",
            "## 输出要求",
            "- 回答要具体，避免空泛占位。",
            "- 如果涉及修改建议，请说明目标文件、关键步骤和验证方式。",
            "- 不要编造不存在的命令执行结果。",
        ]
    )


def call_ollama(model: str, system_prompt: str, user_prompt: str, base_url: str, timeout: int) -> str:
    body = {
        "model": model,
        "stream": False,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "options": {
            "temperature": 0,
            "seed": 42,
        },
    }

    payload = json.dumps(body).encode("utf-8")
    req = request.Request(
        url=f"{base_url.rstrip('/')}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"Ollama HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"Cannot reach Ollama at {base_url}") from exc

    message = data.get("message", {})
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("Ollama returned an empty message")
    return content.strip()


def score_response(sample: dict[str, Any], response_text: str) -> dict[str, Any]:
    scoring = sample.get("scoring", {})
    required_keywords = [str(item) for item in scoring.get("required_keywords", [])]
    forbidden_keywords = [str(item) for item in scoring.get("forbidden_keywords", [])]
    min_chars = int(scoring.get("min_chars", 40))
    max_chars = int(scoring.get("max_chars", 2400))

    normalized = response_text.casefold()
    required_hits = [keyword for keyword in required_keywords if keyword.casefold() in normalized]
    missing_keywords = [keyword for keyword in required_keywords if keyword.casefold() not in normalized]
    forbidden_hits = [keyword for keyword in forbidden_keywords if keyword.casefold() in normalized]

    required_score = len(required_hits) / len(required_keywords) if required_keywords else 1.0
    length_penalty = 0.0 if min_chars <= len(response_text) <= max_chars else 0.15
    forbidden_penalty = min(0.5, len(forbidden_hits) * 0.2)
    score = max(0.0, min(1.0, required_score - length_penalty - forbidden_penalty))

    return {
        "score": round(score, 4),
        "required_hits": required_hits,
        "missing_keywords": missing_keywords,
        "forbidden_hits": forbidden_hits,
        "length": len(response_text),
    }


def evaluate_model(
    model: str,
    samples: list[dict[str, Any]],
    ollama_url: str,
    timeout: int,
) -> list[dict[str, Any]]:
    system_prompt = (
        "你是 YinlinAssistant 的本地编程助手评测版本。"
        "请优先给出工程化、可验证、中文清晰的回答。"
    )
    results: list[dict[str, Any]] = []

    for sample in samples:
        sample_id = str(sample["id"])
        try:
            response_text = call_ollama(
                model=model,
                system_prompt=system_prompt,
                user_prompt=build_prompt(sample),
                base_url=ollama_url,
                timeout=timeout,
            )
            score = score_response(sample, response_text)
            results.append(
                {
                    "id": sample_id,
                    "task_type": sample["task_type"],
                    "model": model,
                    "ok": True,
                    "response": response_text,
                    **score,
                }
            )
        except Exception as exc:
            results.append(
                {
                    "id": sample_id,
                    "task_type": sample.get("task_type", ""),
                    "model": model,
                    "ok": False,
                    "response": "",
                    "score": 0.0,
                    "required_hits": [],
                    "missing_keywords": sample.get("scoring", {}).get("required_keywords", []),
                    "forbidden_hits": [],
                    "length": 0,
                    "error": str(exc),
                }
            )

    return results


def average_score(results: list[dict[str, Any]]) -> float:
    if not results:
        return 0.0
    return round(sum(float(item["score"]) for item in results) / len(results), 4)


def write_report(
    report_path: Path,
    metadata: dict[str, Any],
    samples: list[dict[str, Any]],
    base_results: list[dict[str, Any]],
    candidate_results: list[dict[str, Any]],
) -> None:
    base_by_id = {item["id"]: item for item in base_results}
    candidate_by_id = {item["id"]: item for item in candidate_results}

    lines = [
        "# LoRA Benchmark Report",
        "",
        "## Metadata",
        "",
        f"- Git commit: `{metadata['git_commit']}`",
        f"- Eval file: `{metadata['eval_file']}`",
        f"- Eval SHA-256: `{metadata['eval_sha256']}`",
        f"- Base model: `{metadata['base_model']}`",
        f"- Candidate model: `{metadata['candidate_model']}`",
        f"- Generated at: `{metadata['generated_at']}`",
        "",
        "## Aggregate",
        "",
        "| Model | Average score | Successful calls | Samples |",
        "|---|---:|---:|---:|",
        (
            f"| `{metadata['base_model']}` | {average_score(base_results):.4f} | "
            f"{sum(1 for item in base_results if item['ok'])} | {len(samples)} |"
        ),
        (
            f"| `{metadata['candidate_model']}` | {average_score(candidate_results):.4f} | "
            f"{sum(1 for item in candidate_results if item['ok'])} | {len(samples)} |"
        ),
        "",
        "## Case Scores",
        "",
        "| Case | Task type | Base | Candidate | Delta | Candidate missing keywords |",
        "|---|---|---:|---:|---:|---|",
    ]

    for sample in samples:
        sample_id = str(sample["id"])
        base = base_by_id.get(sample_id, {"score": 0.0})
        candidate = candidate_by_id.get(sample_id, {"score": 0.0, "missing_keywords": []})
        delta = float(candidate["score"]) - float(base["score"])
        missing = ", ".join(candidate.get("missing_keywords", [])) or "-"
        lines.append(
            (
                f"| `{sample_id}` | {sample['task_type']} | {float(base['score']):.4f} | "
                f"{float(candidate['score']):.4f} | {delta:+.4f} | {missing} |"
            )
        )

    lines.extend(
        [
            "",
            "## Reproduce",
            "",
            "```powershell",
            (
                "python scripts/run_lora_benchmark.py "
                f"--base-model {metadata['base_model']} "
                f"--candidate-model {metadata['candidate_model']} "
                f"--eval-file {metadata['eval_file']}"
            ),
            "```",
            "",
        ]
    )

    report_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    args = parse_args()
    eval_file = resolve_path(args.eval_file)
    output_root = resolve_path(args.output_dir)

    if not eval_file.exists():
        print(f"Eval file not found: {eval_file}", file=sys.stderr)
        return 2

    samples = load_jsonl(eval_file)
    if args.limit > 0:
        samples = samples[: args.limit]

    errors = validate_eval_samples(samples)
    if errors:
        print("Dataset validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 2

    print(f"Validated {len(samples)} eval samples from {eval_file}")
    if args.validate_only:
        return 0

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = output_root / timestamp
    output_dir.mkdir(parents=True, exist_ok=True)

    metadata = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "git_commit": git_commit(),
        "eval_file": str(eval_file.relative_to(PROJECT_ROOT) if eval_file.is_relative_to(PROJECT_ROOT) else eval_file),
        "eval_sha256": sha256_file(eval_file),
        "base_model": args.base_model,
        "candidate_model": args.candidate_model,
        "ollama_url": args.ollama_url,
        "sample_count": len(samples),
    }

    print(f"Evaluating base model: {args.base_model}")
    base_results = evaluate_model(args.base_model, samples, args.ollama_url, args.timeout)
    print(f"Evaluating candidate model: {args.candidate_model}")
    candidate_results = evaluate_model(args.candidate_model, samples, args.ollama_url, args.timeout)

    payload = {
        "metadata": metadata,
        "samples": samples,
        "base_results": base_results,
        "candidate_results": candidate_results,
    }

    results_path = output_dir / "results.json"
    report_path = output_dir / "report.md"
    results_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    write_report(report_path, metadata, samples, base_results, candidate_results)

    print(f"Wrote {results_path}")
    print(f"Wrote {report_path}")
    print(f"Base average score: {average_score(base_results):.4f}")
    print(f"Candidate average score: {average_score(candidate_results):.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
