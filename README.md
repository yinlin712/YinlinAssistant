# YinlinAssistant

你好喵👋，本项目YinlinAssistant 是一个面向我的毕业设计《基于 Vibe Coding 的编程助手 Agent 研究与设计》的开源项目原型。它以 VS Code 插件为入口，以 Python Agent 后端为核心，围绕“理解代码、检索项目、规划修改、预览 diff、确认写回”这一条完整链路来设计。目前还在持续更新和开发中

当前仓库已经整理为公开协作版本，适合继续做毕设开发、功能扩展和开源维护。

## 开源信息

- 许可证：[LICENSE](./LICENSE)
- 贡献指南：[CONTRIBUTING.md](./CONTRIBUTING.md)
- 行为准则：[CODE_OF_CONDUCT.md](./CODE_OF_CONDUCT.md)
- 安全策略：[SECURITY.md](./SECURITY.md)

## 当前能力

- 在 VS Code 中读取当前活动文件和选中代码
- 由 Python 后端组织 Agent 工作流并调用 Ollama
- 检索当前项目相关文件，生成项目级修改建议
- 支持三类结构化动作：新建文件、修改旧文件、更新文档
- 在插件侧先展示 diff 预览，再由用户确认是否应用
- Webview 前端已迁移到 React，便于后续继续扩展 UI

## 未来的大饼

- 将LLM更改为经过LoRA微调后的自适应版本
- 使用VRM和Unity技术，增加数字人并再搭载数字人Agent
- 接入OCR和NLP的api，实现更智能化
- 加入快速启动版本（本地exe）

## 技术栈

- 插件壳层：TypeScript + VS Code Extension API（其实就是VScode插件开发框架）
- Agent 后端：Python（经由FastAPI）
- 本地模型：Ollama（DeepSeek）
- Webview 前端：React + esbuild
- Python 运行环境：Conda `CodingAgent`

## 目录结构

```text
.
├─ .github/                    # GitHub 协作配置、Issue/PR 模板、CI 工作流
├─ .vscode/                    # 本仓库的调试与任务配置
├─ backend/                    # Python Agent 后端
├─ docs/                       # 架构说明、边界说明、论文提纲
├─ examples/                   # 演示与测试示例
├─ media/                      # Webview 样式与打包产物目录
├─ src/                        # VS Code 插件端源码
├─ webview-src/                # React Webview 源码
├─ .editorconfig               # 跨语言基础格式约定
├─ .gitattributes              # Git 文本换行与属性配置
├─ .gitignore                  # 构建产物与本地缓存忽略规则
├─ CODE_OF_CONDUCT.md          # 社区行为准则
├─ CONTRIBUTING.md             # 贡献流程与开发约定
├─ LICENSE                     # 开源许可证
├─ SECURITY.md                 # 安全问题披露说明
├─ environment.yml             # Conda 环境定义
├─ package.json                # 插件清单与前端构建脚本
├─ requirements.txt            # Python 后端依赖
└─ README.md                   # 仓库首页说明
```

## 关键目录与文件说明

### `.github/`

- `.github/ISSUE_TEMPLATE/bug_report.yml`
  - 缺陷反馈模板，帮助维护者稳定复现问题
- `.github/ISSUE_TEMPLATE/feature_request.yml`
  - 功能建议模板，约束需求描述格式
- `.github/ISSUE_TEMPLATE/config.yml`
  - Issue 创建入口配置与辅助链接
- `.github/pull_request_template.md`
  - Pull Request 提交模板
- `.github/CODEOWNERS`
  - 默认代码所有者配置
- `.github/workflows/ci.yml`
  - 基础持续集成流程，负责构建插件并检查 Python 后端可编译性

### `backend/`

- `backend/main.py`
  - FastAPI 入口，暴露健康检查与 Agent 调用接口
- `backend/service.py`
  - 后端主服务，负责普通问答、项目级动作规划和结构化结果整理
- `backend/prompt_builder.py`
  - 提示词构造逻辑，区分普通分析、项目修改规划等不同模式
- `backend/structured_response.py`
  - 解析大模型输出的结构化动作
- `backend/agent_workflow.py`
  - 轻量工作流编排层
- `backend/tools/current_file_tool.py`
  - 当前文件分析工具
- `backend/tools/workspace_search_tool.py`
  - 工作区文件检索工具
- `backend/tools/workspace_action_tool.py`
  - 多文件动作的校验与补全过程
- `backend/ollama_client.py`
  - Python 后端与 Ollama 的通信封装

### `src/`

- `src/extension.ts`
  - 插件入口，负责激活扩展与注册命令
- `src/panels/assistantPanel.ts`
  - Webview 面板挂载与 VS Code 消息桥接
- `src/core/agent.ts`
  - 插件侧 Agent 门面，负责采集上下文并向后端发起请求
- `src/core/diffPreview.ts`
  - 将结构化动作转换为 diff 预览文本
- `src/core/actionExecutor.ts`
  - 在用户确认后真正创建或更新文件

### `webview-src/`

- `webview-src/main.tsx`
  - React Webview 入口
- `webview-src/App.tsx`
  - Webview 顶层页面结构
- `webview-src/components/`
  - 面板头部、状态栏、快捷操作、变更预览、对话区、输入区等组件

### 其他重要目录

- `docs/architecture.md`
  - 系统架构说明，适合论文设计章节引用
- `docs/project-boundary.md`
  - 前后端职责边界说明
- `examples/sample_student_manager.py`
  - 用于演示 Agent 分析、解释和改写能力的 Python 示例文件

## 交互流程

1. 用户在插件侧边栏中输入需求或点击快捷操作。
2. 插件端采集当前编辑器上下文、选中代码和工作区路径。
3. Python 后端根据请求类型检索相关文件并组织 Agent 提示词。
4. 后端调用 Ollama 生成结构化修改建议。
5. 插件将建议渲染为 diff 预览，等待用户确认。
6. 用户确认后，插件端执行文件创建、更新或文档修改。

## 本地运行

1. 启动 Python 后端（请确认你有conda环境且py==3.10）

```powershell
& conda run -n CodingAgent python -m uvicorn backend.main:app --reload
```

2. 确认 Ollama 正在运行，并且目标模型已经安装

```powershell
ollama list
```

3. 安装前端依赖并构建项目

```powershell
npm install
npm run build
```

说明：
- `npm run build:extension` 负责编译 VS Code 插件端
- `npm run build:webview` 负责编译 React Webview

4. 在 VS Code 中按 `F5` 调试启动 `Extension Development Host`

## 开发约定

- Python 是后端主语言，Agent 编排、工具调用和模型接入逻辑尽量放在 `backend/`
- TypeScript 只承担插件壳层和 Webview 消息桥接等必要职责
- Webview UI 使用 React 维护，不再继续扩展纯手写 DOM 方案
- 每次调整目录结构或新增关键文件后，需要同步更新本 `README.md`
- 提交信息建议遵循 Conventional Commits，例如 `feat:`、`fix:`、`docs:`、`chore:`

## 适合演示的示例请求

TODO……