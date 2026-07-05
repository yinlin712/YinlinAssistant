# YinlinAssistant

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![VS Code Extension](https://img.shields.io/badge/VS%20Code-Extension-007ACC.svg)](package.json)
[![Python Backend](https://img.shields.io/badge/Python-FastAPI-009688.svg)](requirements.txt)
[![Ollama](https://img.shields.io/badge/Model-Ollama-222222.svg)](config/model_profiles.json)

YinlinAssistant 是毕业设计《基于 Vibe Coding 的编程助手 Agent 研究与设计》的最终实现仓库。项目采用 `VS Code 插件 + Python 后端 + 本地 Ollama 模型 + Embedding/多头注意力上下文选择 + SQLite 记忆 + Vue 数字人 Webview` 的分层架构，目标是实现一个能理解工程上下文、规划项目级修改、展示 diff、确认写回并给出验证建议的本地编程助手 Agent 原型。

> 项目状态：最终毕业设计版本。仓库保留可运行源码、示例工程、模型配置、实验脚本和必要说明；本地 AIRI 仓库、运行日志、实验输出、论文中间稿、PPT 和大体积个人材料不提交。

## 目录

- [项目成果](#项目成果)
- [系统架构](#系统架构)
- [核心能力](#核心能力)
- [快速开始](#快速开始)
- [演示与实验](#演示与实验)
- [目录结构](#目录结构)
- [配置说明](#配置说明)
- [仓库边界](#仓库边界)
- [贡献、安全与许可证](#贡献安全与许可证)

## 项目成果

本项目已经完成一个较完整的编程助手 Agent 原型，重点成果包括：

- VS Code 侧边栏交互：聊天、当前文件改写、项目级修改提案、diff 预览、确认写回。
- Python 后端 Agent 编排：请求分类、Prompt 构造、工具调用、模型请求、流式响应和演示兜底。
- 上下文选择模块：基于 `bge-m3` Embedding、片段级候选切分、多头注意力重排、调用链扩展和 source-aware 记忆约束。
- SQLite 记忆库：保存历史对话、长期偏好和上下文选择诊断，可通过 `/memory` 接口查看或清空。
- 自动验证辅助：根据项目结构推断测试命令，并把测试结果解释回传给前端。
- 数字人和语音演示：Webview 数字人状态展示、本地语音桥接、AIRI 兼容转写配置和答辩固定转写模式。
- 示例工程：`examples/student_score_project/` 用于展示代码解释、项目级检索、修改规划、风险提示和测试闭环。
- 可解释实验：上下文选择消融实验可生成 CSV、Markdown 和图表，用于论文与答辩说明。

主实验结论摘要：

| 方案 | Hit@1 | Hit@3 | Workspace Hit@1 | Workspace Hit@3 | MRR |
|---|---:|---:|---:|---:|---:|
| 仅 Embedding | 0.380 | 0.440 | 0.380 | 0.440 | 0.420 |
| Embedding + 多头注意力 | 0.440 | 0.500 | 0.440 | 0.500 | 0.471 |
| Embedding + 多头注意力 + 调用链 | 0.600 | 0.780 | 0.600 | 0.780 | 0.704 |
| Embedding + 多头注意力 + 调用链 + 记忆 | 0.760 | 0.860 | 0.760 | 0.860 | 0.830 |

## 系统架构

```text
用户请求
  -> VS Code 插件采集编辑器、活动文件和工作区信息
  -> Python 后端分类请求
  -> 工作区检索、语义检索、SQLite 记忆召回、文件片段切分
  -> Embedding + 多头注意力 + 调用链扩展 + source-aware 重排
  -> Ollama 本地模型生成回答或项目级修改方案
  -> Webview 展示 Markdown、上下文诊断、提案、diff 和验证建议
  -> 用户确认后由插件端写回文件
```

插件端负责编辑器交互、diff 预览、文件写回和 Webview；Python 后端负责 Agent 编排、模型调用、记忆和上下文选择；Ollama 负责本地模型推理；AIRI 作为可选本地语音服务，不随本仓库提交。

## 核心能力

### 上下文选择

- `backend/ml/embedding_provider.py`：统一 Embedding 提供层，默认调用 Ollama `bge-m3`，不可用时回退到哈希向量。
- `backend/ml/context_candidate.py`：把 Python、TypeScript、Vue、Markdown 等文件切分为函数、方法、块或段落级候选，并支持 Python 一跳调用链扩展。
- `backend/ml/attention_memory.py`：对工作区片段、历史对话和长期记忆做多头注意力重排，输出权重、Top 片段和诊断信息。
- `backend/ml/context_selection_experiment.py`：运行上下文选择消融实验，输出 CSV、Markdown 和图表。

### Agent 后端

- `backend/main.py`：FastAPI 入口，提供 `/health`、`/generate`、`/stream-generate`、`/memory`、`/voice-bridge/*` 等接口。
- `backend/service.py`：核心服务，编排普通问答、当前文件改写、项目级提案、测试解释、记忆写入和答辩演示稳定逻辑。
- `backend/prompt_builder.py`：维护普通问答、当前文件改写、项目级动作规划、修复建议和测试解释 Prompt。
- `backend/tools/`：工作区检索、语义排序、动作准备、风险评分和测试计划推断。

### VS Code 与 Webview

- `src/extension.ts`：插件入口，注册命令、侧边栏和语音服务管理。
- `src/core/agent.ts`：采集编辑器上下文并调用后端。
- `src/panels/assistantPanel.ts`：连接 Webview、Agent、diff 预览、待确认方案和语音桥接。
- `webview-src/App.vue`：Webview 顶层状态管理。
- `webview-src/components/`：聊天列表、输入框、提案面板、状态栏和数字人组件。

## 快速开始

### 1. 克隆仓库

```powershell
git clone https://github.com/yinlin712/YinlinAssistant.git
cd YinlinAssistant
```

### 2. 准备 Python 环境

```powershell
conda env create -f environment.yml
conda activate CodingAgent
```

或直接安装依赖：

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
ollama pull bge-m3
```

### 5. 启动后端

```powershell
python -m uvicorn backend.main:app --reload
```

健康检查：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

### 6. 构建并调试插件

```powershell
npm run build
```

然后在 VS Code 中按 `F5` 启动 Extension Development Host，并打开侧边栏 `Code Agent`。

## 演示与实验

### 答辩稳定演示

普通问答固定演示输入：

```text
你好，请介绍一下你自己
```

项目级修改固定演示输入：

```text
帮我修改项目使其更加适配后续接口扩展
```

语音演示默认启用固定转写模式，点击麦克风后约 5 秒会稳定得到：

```text
你好，请介绍一下你自己
```

如需恢复真实语音识别：

```powershell
$env:CODE_AGENT_DEMO_VOICE="0"
```

### 上下文选择实验

运行消融实验：

```powershell
python -m backend.ml.context_selection_experiment --top-k 8
```

实验输出默认写入 `log/context_selection_experiments/<timestamp>/`，该目录属于本地运行产物，不提交到仓库。

### 常用验证命令

```powershell
python -m compileall backend
npm run build
```

## 目录结构

```text
.
├─ backend/                 Python 后端、Agent 编排、记忆、上下文选择和工具层
├─ config/                  本地模型 profile 配置
├─ data/                    本地运行数据目录和小规模模型样本
├─ docs/                    项目说明和论文相关 Markdown 文档
├─ examples/                单文件与多文件演示工程
├─ media/                   VS Code Webview 静态资源和样式
├─ models/                  本地模型适配配置与 Modelfile
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

```powershell
$env:OLLAMA_MODEL_PROFILE="qwen_local_default"
$env:OLLAMA_MODEL="qwen2.5-coder:7b"
$env:OLLAMA_FALLBACK_MODEL="deepseek-r1:7b"
$env:OLLAMA_BASE_URL="http://127.0.0.1:11434"
$env:CODE_AGENT_EMBEDDING_MODEL="bge-m3"
```

### 语音与 AIRI

常用 VS Code 设置：

```text
vibeCodingAgent.enableVoiceInteraction = true
vibeCodingAgent.voiceApiBaseUrl = http://127.0.0.1:3000
vibeCodingAgent.voiceTranscriptionModel = whisper-1
vibeCodingAgent.voiceLanguage = zh
vibeCodingAgent.autoStartVoiceService = true
vibeCodingAgent.voiceServicePath = D:\\Graduation Project\\airi
vibeCodingAgent.voiceServiceStartCommand = pnpm dev:server
```

`airi/` 是本地外部项目目录，只作为可选语音服务依赖，不进入本仓库。

## 仓库边界

适合提交：

- 核心源码：`backend/`、`src/`、`webview-src/`、`virtual/`。
- 配置与依赖：`package.json`、`requirements.txt`、`environment.yml`、`config/`。
- 小规模示例工程、模型配置样例和可复现实验脚本。
- Markdown 形式的项目说明、架构说明和必要开发文档。

不适合提交：

- `airi/` 本地外部仓库。
- `.tmp/`、`log/`、`outputs/`、`dist/`、`node_modules/` 等生成产物。
- 本地 SQLite 记忆库、`.env`、密钥、个人配置。
- 论文 doc/docx/pdf、答辩 PPT、Office 临时锁文件和大体积截图材料。

## 贡献、安全与许可证

- 贡献指南：[CONTRIBUTING.md](CONTRIBUTING.md)
- 行为准则：[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)
- 安全策略：[SECURITY.md](SECURITY.md)
- 许可证：[MIT License](LICENSE)

如果发现安全问题，请按 [SECURITY.md](SECURITY.md) 中的方式报告，不要在公开 issue 中暴露敏感信息。
