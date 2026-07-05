# Yinlin Qwen Coding Agent Adapter

本目录是 `models/lora/modelfiles/yinlin-qwen-coding-agent.Modelfile` 期望读取的 LoRA adapter 导出目录。

大型 adapter 权重不提交到仓库。完成训练后，请把导出的 adapter 文件放到本目录，再在仓库根目录执行：

```powershell
ollama create yinlin-qwen-coding-agent -f models/lora/modelfiles/yinlin-qwen-coding-agent.Modelfile
```

创建本地 Ollama 别名后，可以运行 benchmark 比较基础模型与 LoRA-ready 模型：

```powershell
python scripts/run_lora_benchmark.py --base-model qwen2.5-coder:7b --candidate-model yinlin-qwen-coding-agent
```
