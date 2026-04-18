# YinlinAssistant

YinlinAssistant 是毕业设计《基于 Vibe Coding 的编程助手 Agent 研究与设计》的实现仓库。项目采用“VS Code 插件 + Python 后端 + 本地 Ollama 模型”的结构，用于验证代码理解、项目检索、修改规划、diff 预览与确认写回等能力。

## 项目结构

```text
.
├─ .github/                GitHub 协作配置
├─ .vscode/                VS Code 调试与任务配置
├─ backend/                Python 后端与 Agent 逻辑
├─ config/                 模型档案配置
├─ data/                   LoRA 训练与评估数据目录
├─ docs/                   架构与论文相关文档
├─ examples/               演示样例
├─ media/                  Webview 样式与打包产物
├─ models/                 LoRA 适配器与 Modelfile 目录
├─ src/                    VS Code 插件源码
├─ webview-src/            React Webview 源码
├─ environment.yml         Conda 环境定义
├─ package.json            插件清单与前端构建脚本
├─ requirements.txt        Python 依赖
└─ README.md
```

## 关键目录

### `backend/`

- `backend/main.py`
  - FastAPI 入口，提供健康检查、普通生成和流式生成接口。
- `backend/service.py`
  - 后端主服务，负责编排问答、当前文件改写和项目级多文件方案。
- `backend/request_classifier.py`
  - 判断请求属于普通问答、当前文件改写还是项目级修改。
- `backend/prompt_builder.py`
  - 维护各类提示词模板。
- `backend/tools/`
  - 放置当前文件分析、工作区检索、动作规划和动作校验工具。

### `src/`

- `src/extension.ts`
  - 插件入口，注册侧边栏、命令和 diff 预览服务。
- `src/panels/assistantPanel.ts`
  - 连接 Webview、插件端 Agent 与文件应用流程。
- `src/core/agent.ts`
  - 负责上下文采集与后端调用。
- `src/core/actionExecutor.ts`
  - 负责真正创建或更新工作区文件。
- `src/core/editorDiffPreview.ts`
  - 负责编辑器原生 diff 预览。

### `webview-src/`

- `webview-src/App.tsx`
  - Webview 顶层页面。
- `webview-src/components/ChatList.tsx`
  - 对话消息列表。
- `webview-src/components/ProposalPanel.tsx`
  - 待确认方案面板。
- `webview-src/components/Composer.tsx`
  - 输入区。
- `webview-src/components/MarkdownContent.tsx`
  - Markdown 渲染。

### `examples/`

- `examples/sample_student_manager.py`
  - 单文件演示样例，适合测试当前文件分析与直接改写。
- `examples/student_score_project/`
  - 多文件演示工程，作为默认测试工程使用。
  - 该目录应保持为可运行的基线版本，不直接写入临时演示结果。

## 当前能力

- 普通问答与代码解释
- 当前文件直接改写
- 项目级多文件方案规划
- 编辑器原生 diff 预览
- Markdown 回答渲染
- Qwen 本地模型接入与 DeepSeek 兼容兜底
- LoRA 训练目录、适配器目录和 Ollama Modelfile 目录预留

## 模型与 LoRA 预留

- 默认模型：`qwen2.5-coder:7b`
- 兼容兜底模型：`deepseek-r1:7b`
- 模型档案：`config/model_profiles.json`
- LoRA 训练数据目录：`data/lora/train/`
- LoRA 评估数据目录：`data/lora/eval/`
- LoRA 适配器目录：`models/lora/adapters/`
- Ollama Modelfile 目录：`models/lora/modelfiles/`

## 运行方式

### 1. 启动 Python 后端

```powershell
& 'E:\ANACONDA\condabin\conda.bat' run -n CodingAgent python -m uvicorn backend.main:app --reload
```

### 2. 检查本地模型

```powershell
ollama list
```

建议至少准备：

```powershell
ollama pull qwen2.5-coder:7b
ollama pull deepseek-r1:7b
```

### 3. 构建插件

```powershell
npm install
npm run build
```

### 4. 调试插件

- 在 VS Code 中按 `F5`
- 默认调试配置会禁用其他扩展
- 扩展开发宿主会打开 `examples/student_score_project/`

## 开发约定

- Python 负责后端 Agent 编排、提示词和工具逻辑。
- TypeScript 负责插件壳层、编辑器交互和 Webview 桥接。
- Webview UI 使用 React 维护。
- 调整目录结构或新增关键文件后，需要同步更新本 README。
- 提交信息遵循 Conventional Commits。

## 常用演示提示词

- `请解释当前文件的主要结构，并给出可执行的优化建议。`
- `帮我继续封装这个函数。`
- `请检索当前项目相关文件，并规划一组待确认的多文件修改方案。`
- `请为当前项目生成一组待确认的文档更新方案。`
