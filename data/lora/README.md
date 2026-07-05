# LoRA 数据与评估集

本目录存放 YinlinAssistant 面向编程助手任务的 LoRA 指令微调样本和本地评估样本。仓库只提交小规模、可审查的数据样例，不提交模型权重或大型训练产物。

## 目录结构

```text
data/lora/
├─ train/
│  └─ coding_assistant_train.jsonl
├─ eval/
│  └─ coding_assistant_eval.jsonl
└─ README.md
```

## 训练样本格式

训练文件使用 `jsonl`，每行是一条独立 JSON 对象：

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | string | 样本唯一标识 |
| `task_type` | string | 任务类型，例如 `code_review`、`project_planning`、`test_planning` |
| `instruction` | string | 用户指令 |
| `input` | string | 代码片段、文件路径或项目上下文 |
| `output` | string | 期望模型生成的中文回答 |
| `source` | string | 样本来源或关联目录 |
| `tags` | string[] | 可选标签，用于后续筛选 |

示例：

```json
{"id":"train_test_plan_student_project","task_type":"test_planning","instruction":"为学生成绩示例工程生成一个轻量验证计划。","input":"工程目录：examples/student_score_project/。","output":"轻量验证计划可以分三层：...","source":"examples/student_score_project","tags":["test","verification"]}
```

## 评估样本格式

评估文件同样使用 `jsonl`。为了能在本地稳定比较基础模型和 LoRA-ready 模型，每条评估样本额外包含可解释评分规则：

| 字段 | 类型 | 说明 |
|---|---|---|
| `expected_behavior` | string | 人类可读的期望行为 |
| `scoring.required_keywords` | string[] | 回答中应出现的关键证据 |
| `scoring.forbidden_keywords` | string[] | 回答中不应出现的明显错误表达 |
| `scoring.min_chars` | number | 最短回答长度 |
| `scoring.max_chars` | number | 最长回答长度 |

评分脚本不会声称替代人工评审；它只提供可复现的轻量证据，帮助展示基础模型与 LoRA-ready 模型在项目任务上的差异。

## 本地验证

只校验数据格式：

```powershell
python scripts/run_lora_benchmark.py --validate-only
```

比较基础模型与 LoRA-ready 模型：

```powershell
python scripts/run_lora_benchmark.py `
  --base-model qwen2.5-coder:7b `
  --candidate-model yinlin-qwen-coding-agent
```

输出文件默认写入：

```text
outputs/lora-benchmark/<timestamp>/
├─ results.json
└─ report.md
```

## 与模型档案的关系

- 基础模型档案位于 `config/model_profiles.json` 的 `qwen_local_default`。
- LoRA-ready 档案位于 `config/model_profiles.json` 的 `qwen_lora_ready`。
- Ollama Modelfile 位于 `models/lora/modelfiles/yinlin-qwen-coding-agent.Modelfile`。
- LoRA adapter 导出目录为 `models/lora/adapters/yinlin-qwen-coding-agent/`。

创建本地 Ollama 别名：

```powershell
ollama create yinlin-qwen-coding-agent -f models/lora/modelfiles/yinlin-qwen-coding-agent.Modelfile
```

如果 adapter 权重尚未导出，上述创建命令会失败；此时仍可使用 `--validate-only` 验证数据集和评估流程。
