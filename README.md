# YinlinAssistant

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![VS Code Extension](https://img.shields.io/badge/VS%20Code-Extension-007ACC.svg)](package.json)
[![Python Backend](https://img.shields.io/badge/Python-FastAPI-009688.svg)](requirements.txt)
[![Ollama](https://img.shields.io/badge/Model-Ollama-222222.svg)](config/model_profiles.json)

YinlinAssistant 是毕业设计《基于 Vibe Coding 的编程助手 Agent 研究与设计》的实现仓库。项目采用 `VS Code 插件 + Python 后端 + 本地 Ollama 模型 + Vue Webview + 数字人交互` 的分层结构，目标是构建一个可以理解工程上下文、规划修改、展示 diff、确认写回并给出验证建议的本地编程助手原型。

> 项目状态：毕业设计原型。核心链路可用于本地演示和论文答辩，模型权重、运行日志和大型实验产物不提交到仓库。

## 目录

- [功能特性](#功能特性)
- [架构概览](#架构概览)
- [技术栈](#技术栈)
- [快速开始](#快速开始)
- [模型与 LoRA Benchmark](#模型与-lora-benchmark)
- [开发与验证](#开发与验证)
- [目录结构](#目录结构)
- [配置说明](#配置说明)
- [贡献、安全与许可证](#贡献安全与许可证)

## 功能特性

- VS Code 侧边栏聊天界面，支持普通问答、代码解释和当前文件修改请求。
- Python FastAPI 后端统一处理请求分类、Prompt 构造、工具编排和 Ollama 调用。
- 项目级修改以待确认文件动作呈现，先展示 diff，再由用户确认写回。
- 工作区检索、语义排序、风险评分和测试建议工具，为项目级任务提供上下文证据。
- Vue Webview 前端支持 Markdown 渲染、提案面板、状态栏和数字人展示。
- 本地语音桥接和 AIRI 兼容转写接口预留，用于扩展语音交互演示。
- LoRA-ready 模型档案、数据格式、训练样本、评估样本和可复现 benchmark 脚本。

## 架构概览

```text
用户请求
  -> VS Code 插件采集编辑器与工作区上下文
  -> Python 后端分类请求并构造 Prompt
  -> 工作区工具补充相关文件、风险和验证建议
  -> Ollama 本地模型生成回答或修改方案
  -> Webview 展示回复、diff 预览和待确认动作
  -> 用户确认后由插件端写回文件
```

后端和插件端保持解耦：插件负责编辑器交互和 UI，Python 后端负责 Agent 编排与模型调用，模型配置集中在 `config/model_profiles.json`。

## 技术栈

| 模块 | 技术 |
|---|---|
| VS Code 插件 | TypeScript、VS Code Extension API |
| Webview | Vue 3、Vite、Markdown 渲染 |
| 后端服务 | Python、FastAPI、Uvicorn |
| 本地模型 | Ollama、`qwen2.5-coder:7b`、`deepseek-r1:7b` |
| 模型实验 | LoRA-ready Modelfile、JSONL 数据集、标准库评估脚本 |
| 数字人扩展 | VRM / AIRI 兼容接口预留 |

## 快速开始

### 1. 克隆仓库

```powershell
git clone https://github.com/yinlin712/YinlinAssistant.git
cd YinlinAssistant
```

### 2. 准备 Python 环境

推荐使用 Conda：

```powershell
conda env create -f environment.yml
conda activate CodingAgent
```

也可以直接安装 Python 依赖：

```powershell
python -m pip install -r requirements.txt
```

### 3. 安装前端依赖

```powershell
npm install
```

### 4. 准备 Ollama 模型

```powershell
ollama pull qwen2.5-coder:7b
ollama pull deepseek-r1:7b
```

### 5. 启动 Python 后端

```powershell
python -m uvicorn backend.main:app --reload
```

健康检查：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

### 6. 构建并调试 VS Code 插件

```powershell
npm run build
```

然后在 VS Code 中按 `F5` 启动 Extension Development Host，并打开侧边栏 `Code Agent`。

## 模型与 LoRA Benchmark

模型档案位于：

```text
config/model_profiles.json
```

当前包含三类档案：

| Profile | 用途 |
|---|---|
| `qwen_local_default` | 默认基础模型，对应 `qwen2.5-coder:7b` |
| `deepseek_compat` | 本地只有 DeepSeek 模型时的兼容兜底 |
| `qwen_lora_ready` | LoRA-ready 档案，指向实际 Modelfile、adapter 目录和 benchmark 数据 |

### 数据集

LoRA 数据位于：

```text
data/lora/
├─ train/coding_assistant_train.jsonl
└─ eval/coding_assistant_eval.jsonl
```

数据格式说明见 [data/lora/README.md](data/lora/README.md)。训练样本覆盖代码审查、项目级规划、测试建议、README 编写和 Agent 安全行为；评估样本使用 `required_keywords`、`forbidden_keywords` 和长度范围形成轻量可复现评分。

### 创建 LoRA-ready Ollama 别名

LoRA Modelfile 位于：

```text
models/lora/modelfiles/yinlin-qwen-coding-agent.Modelfile
```

训练后的 adapter 权重应导出到：

```text
models/lora/adapters/yinlin-qwen-coding-agent/
```

创建本地模型别名：

```powershell
ollama create yinlin-qwen-coding-agent -f models/lora/modelfiles/yinlin-qwen-coding-agent.Modelfile
```

如果 adapter 权重尚未导出，创建命令会失败；这不会影响数据集格式校验。

### 运行 benchmark

只验证数据集格式：

```powershell
python scripts/run_lora_benchmark.py --validate-only
```

比较基础模型和 LoRA-ready 模型：

```powershell
python scripts/run_lora_benchmark.py `
  --base-model qwen2.5-coder:7b `
  --candidate-model yinlin-qwen-coding-agent
```

默认输出：

```text
outputs/lora-benchmark/<timestamp>/
├─ results.json
└─ report.md
```

报告会记录 Git commit、评估集 SHA-256、模型名称、每条样本得分和候选模型相对基础模型的差异，方便答辩时展示“基础模型 vs LoRA-ready 模型”的证据链。

## 开发与验证

常用命令：

```powershell
python -m compileall backend
npm run build
python scripts/run_lora_benchmark.py --validate-only
```

构建脚本：

| 命令 | 说明 |
|---|---|
| `npm run build` | 构建插件和 Webview |
| `npm run build:extension` | 只构建 TypeScript 插件 |
| `npm run build:webview` | 只构建 Vue Webview |
| `npm run watch` | 监听插件端 TypeScript 编译 |
| `npm run package` | 打包 VS Code 扩展 |

后端运行时默认使用：

```text
http://127.0.0.1:8000
```

Ollama 默认使用：

```text
http://127.0.0.1:11434
```

## 目录结构

```text
.
├─ backend/                 Python 后端、Agent 编排和工具层
├─ config/                  模型 profile 配置
├─ data/                    LoRA 数据与本地运行数据目录
├─ docs/                    架构、论文和项目文档
├─ examples/                演示样例工程
├─ media/                   VS Code Webview 静态资源
├─ models/                  LoRA adapter 目录与 Ollama Modelfile
├─ scripts/                 本地评估和辅助脚本
├─ src/                     VS Code 插件源码
├─ virtual/                 数字人运行时协议和配置
├─ webview-src/             Vue Webview 源码
├─ environment.yml          Conda 环境定义
├─ package.json             插件清单与前端构建脚本
├─ requirements.txt         Python 依赖
└─ README.md
```

## 配置说明

### 后端模型

可通过环境变量覆盖模型选择：

```powershell
$env:OLLAMA_MODEL_PROFILE="qwen_local_default"
$env:OLLAMA_MODEL="qwen2.5-coder:7b"
$env:OLLAMA_FALLBACK_MODEL="deepseek-r1:7b"
$env:OLLAMA_BASE_URL="http://127.0.0.1:11434"
```

### VS Code 设置项

常用设置：

```text
vibeCodingAgent.modelProvider = local
vibeCodingAgent.localModelEndpoint = http://127.0.0.1:8000/generate
vibeCodingAgent.enableAvatar = true
vibeCodingAgent.avatarMode = vrm
vibeCodingAgent.enableVoiceInteraction = true
vibeCodingAgent.voiceApiBaseUrl = http://127.0.0.1:3000
```

### 不应提交的内容

- 本地模型权重和 LoRA adapter 大文件。
- 运行日志、benchmark 输出和临时实验产物。
- 本地 `.env`、API key、编辑器私有配置。
- 论文中间稿、Office 临时锁文件和个人材料。

## 贡献、安全与许可证

- 贡献指南：[CONTRIBUTING.md](CONTRIBUTING.md)
- 行为准则：[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)
- 安全策略：[SECURITY.md](SECURITY.md)
- 许可证：[MIT License](LICENSE)

提交改动前建议至少运行：

```powershell
python -m compileall backend
npm run build
python scripts/run_lora_benchmark.py --validate-only
```

如果发现安全问题，请按 [SECURITY.md](SECURITY.md) 中的方式报告，不要在公开 issue 中暴露敏感信息。
