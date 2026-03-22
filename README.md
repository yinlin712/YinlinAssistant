# Vibe Coding Agent

这是一个面向毕业设计《基于 Vibe Coding 的编程助手 Agent 研究与设计》的 VS Code 插件原型项目。

当前项目采用清晰的前后端分层：
- `src/`：VS Code 插件端，负责界面展示、收集编辑器上下文、显示 diff 预览、确认后执行文件写回
- `backend/`：Python 后端，负责 Agent 工作流、工作区检索、提示词组织、结构化动作生成、调用 Ollama
- `webview-src/`：React Webview 前端源码
- `media/`：Webview 打包产物和样式资源
- `docs/`：系统架构、前后端边界说明、论文提纲等文档

后续每次功能更新后，都应同步更新本 README，保证目录说明和文件职责始终可追踪。

## 当前技术栈

- VS Code 插件壳层：TypeScript
- Agent 核心后端：Python
- 本地模型运行时：Ollama
- Python 环境：Conda `CodingAgent`

## 项目目录说明

```text
.
├─ backend/                  # Python 后端，真正的 Agent 逻辑在这里
├─ docs/                     # 架构设计和论文相关文档
├─ examples/                 # 演示和测试用示例代码
├─ webview-src/              # React Webview 前端源码
├─ media/                    # Webview 前端资源
├─ src/                      # VS Code 插件端
├─ .vscode/                  # 调试配置、任务配置、解释器配置
├─ environment.yml           # Conda 环境定义
├─ requirements.txt          # Python 依赖
├─ package.json              # VS Code 插件清单与配置项
├─ tsconfig.json             # TypeScript 编译配置
└─ README.md                 # 项目总览与目录导航
```

## 关键目录与文件功能

### 1. `backend/`：Python 后端

- `backend/main.py`
  - FastAPI 入口，向插件暴露 `/health` 和 `/generate`
- `backend/service.py`
  - 后端主服务
  - 负责区分“普通问答”和“项目级变更规划”两种模式
- `backend/agent_workflow.py`
  - 轻量级 Agent 编排层
  - 负责串联当前文件分析、工作区检索、动作校验
- `backend/models.py`
  - 后端请求/响应模型定义
  - 包括结构化文件动作 `create_file`、`update_file`、`update_documentation`
- `backend/ollama_client.py`
  - 封装对本机 Ollama 服务的调用
- `backend/prompt_builder.py`
  - 负责拼装提示词
  - 区分普通问答提示词和“项目级变更方案”提示词
- `backend/request_classifier.py`
  - 判断用户请求是否属于“需要真正修改项目”的类型
- `backend/structured_response.py`
  - 解析模型返回的结构化动作方案
- `backend/icon.jpg`
  - 当前插件面板使用的角色头像图片

### 2. `backend/tools/`：后端工具层

- `backend/tools/current_file_tool.py`
  - 分析当前活动文件
  - 负责统计文件结构、类、函数、风险点
- `backend/tools/workspace_search_tool.py`
  - 在工作区中检索与当前需求相关的多个文件
  - 为模型提供项目级上下文
- `backend/tools/workspace_action_tool.py`
  - 对模型生成的多文件动作做安全校验
  - 补齐原始内容，用于前端生成 diff 和做冲突检测

### 3. `src/`：VS Code 插件端

- `src/extension.ts`
  - 插件入口
  - 注册侧边栏视图、命令和编辑器事件
- `src/panels/assistantPanel.ts`
  - 插件主面板
  - 负责把 Webview 挂载到 React 前端，并处理消息桥接

### 4. `src/core/`：插件核心逻辑

- `src/core/agent.ts`
  - 插件侧 Agent 门面
  - 负责收集编辑器上下文、调用后端、在确认后执行动作
- `src/core/types.ts`
  - 插件端类型定义
- `src/core/actionExecutor.ts`
  - 真正执行文件创建、文件更新、文档更新的落盘逻辑
- `src/core/diffPreview.ts`
  - 生成简化版 unified diff 预览文本

### 5. `src/core/providers/`：模型提供者适配层

- `src/core/providers/localModelProvider.ts`
  - 调用 Python 后端接口
- `src/core/providers/mockProvider.ts`
  - 调试 UI 时使用的假响应提供者

### 6. `webview-src/`：React Webview 前端源码

- `webview-src/main.tsx`
  - React 入口文件
- `webview-src/App.tsx`
  - Webview 顶层组件
  - 负责把界面整理成“头部概览 -> 快捷任务 -> 待确认变更 -> 对话记录 -> 输入区”的单列工作流布局
- `webview-src/components/`
  - React 组件目录
  - 当前包含头部概览、状态栏、快捷任务、变更预览、聊天列表、输入框等组件
- `webview-src/types.ts`
  - Webview 前端的消息协议和类型定义
- `webview-src/vscode.ts`
  - 对 `acquireVsCodeApi()` 的轻量封装

### 7. `media/`：Webview 打包产物与样式资源

- `media/styles.css`
  - React Webview 使用的全局样式表
  - 当前设计目标是“信息层级清晰、侧边栏占用克制、适合后续扩展”
- `media/webview.js`
  - 由 `webview-src/` 通过 esbuild 打包生成的浏览器脚本
- `media/icon.svg`
  - 预留的图标资源

### 8. `docs/`：项目文档

- `docs/architecture.md`
  - 系统架构说明
- `docs/project-boundary.md`
  - 前后端职责边界说明
- `docs/thesis-outline.md`
  - 毕设论文提纲草案

### 9. `examples/`：示例代码

- `examples/sample_student_manager.py`
  - 用于演示“分析文件”“解释代码”“生成修改方案”的示例 Python 文件

## 当前 Agent 能力

- 读取当前活动文件
- 分析 Python 文件中的结构和基础风险
- 根据用户请求检索工作区中的多个相关文件
- 生成结构化项目变更方案
- 前端界面已改为 React 组件架构，便于后续继续扩展功能面板
- 插件 UI 已整理为更简洁的单列工作流布局，更适合 VS Code 侧边栏使用
- 支持三类动作一起编排
  - 创建新文件
  - 修改已有文件
  - 更新说明文档
- 先生成 diff 预览，再由用户确认是否真正应用
- 在应用前检查目标文件是否已变化，避免覆盖新编辑

## 当前工作流

1. 用户在插件中提出需求
2. VS Code 插件收集当前编辑器上下文
3. Python 后端分析当前文件，并检索工作区相关文件
4. 后端调用 Ollama，生成结构化文件动作方案
5. 插件将动作转换为 diff 预览显示在侧边栏
6. 用户点击“确认应用”后，插件才真正写回文件

## 当前 UI 设计原则

- 以“工作流清晰”为第一目标，而不是做宣传页式布局
- 把状态、快捷任务、待确认变更、对话记录分成明确区域
- 减少大面积装饰性视觉元素，优先保证信息可扫描性
- 保留 React 组件化结构，方便后续继续扩展多步骤 Agent 交互

## 运行方式

1. 启动 Python 后端

```powershell
& 'E:\ANACONDA\condabin\conda.bat' run -n CodingAgent python -m uvicorn backend.main:app --reload
```

2. 确认 Ollama 已经运行，并且目标模型存在

```powershell
ollama list
```

3. 构建 VS Code 插件

```powershell
npm run build
```

说明：
- `npm run build:extension` 负责编译 VS Code 插件端 TypeScript
- `npm run build:webview` 负责编译 React Webview 前端

4. 在 VS Code 中按 `F5` 启动 Extension Development Host

## 快速演示建议

你可以先打开：
- `examples/sample_student_manager.py`

然后在插件中尝试这些请求：

```text
请分析当前文件的结构，并指出可维护性问题。
```

```text
请先检索当前项目相关文件，再规划一组待确认的项目级修改方案，必要时可以同时包含新增文件、修改旧文件和更新文档。
```

```text
请先检索当前项目中与功能说明相关的文件，并规划一组待确认的文档更新方案，优先考虑 README.md 和 docs 目录。
```

## 默认配置

- Ollama base URL: `http://127.0.0.1:11434`
- Ollama model: `deepseek-r1:7b`
- Python backend endpoint: `http://127.0.0.1:8000/generate`
- Conda env: `CodingAgent`

## 仓库管理约定

- `media/webview.js` 属于前端打包产物，不直接提交源码仓库
- `__pycache__/`、`*.pyc` 等 Python 缓存文件不纳入版本控制
- `.vscode/settings.json` 属于本机环境配置，不作为跨机器共享配置提交
- `.vscode/launch.json`、`.vscode/tasks.json` 保留在仓库中，方便项目调试和演示

## 开发原则

- 与 VS Code 生命周期强相关的代码写在 `src/`
- 与模型、工具、Agent 工作流相关的代码写在 `backend/`
- 如果未来可能被其他前端复用，优先写在 Python 后端
- 任何涉及项目结构变化的功能，都应同步更新本 README
- 注释和结构尽量面向计算机初学者保持清晰
