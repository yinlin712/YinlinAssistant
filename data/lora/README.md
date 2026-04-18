# LoRA 数据目录

本目录用于存放后续 LoRA 微调阶段需要维护的数据与说明，不直接存放大型模型权重。

## 子目录说明

- `train/`
  - 训练样本目录。建议按任务来源拆分子目录，例如 `code-edit/`、`code-review/`、`project-planning/`。
- `eval/`
  - 验证与回归测试样本目录。用于检查微调前后在项目级修改、单文件改写与中文问答上的稳定性。

## 推荐数据格式

- 指令微调建议优先使用 `jsonl`
- 单条样本建议包含以下字段：
  - `instruction`
  - `input`
  - `output`
  - `task_type`
  - `source`

## 与推理层的关系

- 训练数据目录只负责样本管理
- LoRA 适配器导出目录建议放在仓库根目录下的 `models/lora/adapters/`
- Ollama `Modelfile` 建议放在 `models/lora/modelfiles/`
- 当前运行时会通过 `config/model_profiles.json` 选择基础模型、LoRA 目标别名和备用模型
