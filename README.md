# YinlinAssistant

YinlinAssistant 是一个面向毕业设计《基于 Vibe Coding 的编程助手 Agent 研究与设计》的开源项目原型。项目以 VS Code 插件为入口，以 Python Agent 后端为核心，围绕“理解代码、检索项目、规划修改、预览 diff、确认写回”这一条完整链路进行设计，当前仍在持续迭代。

当前仓库已经公开，适合继续开展毕设开发、功能扩展与开源协作。

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
- 当本地模型不能稳定返回多文件 XML 时，会自动退回到“先选目标文件，再逐文件生成完整内容”的兜底链路
- 针对 Python 文件增加了语法校验与单文件修复回合，尽量把不可执行代码挡在预览之前
- 对示例文件 `sample_student_manager.py` 额外提供了演示保底方案，确保弱模型环境下仍能稳定展示 diff 预览和确认应用流程
- Webview 前端已迁移到 React，便于后续继续扩展 UI

## 后续规划

- 将本地模型切换为经过 LoRA 微调的适配版本
- 使用 VRM 与 Unity 技术增加数字人形象，并扩展数字人 Agent 交互能力
- 接入 OCR 与 NLP 相关能力，补充多模态理解与辅助分析
- 提供面向演示场景的快速启动版本

## 技术栈

- 插件壳层：TypeScript + VS Code Extension API
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
  - 后端主服务，负责普通问答、项目级动作规划、逐文件兜底生成和结构化结果整理
- `backend/prompt_builder.py`
  - 提示词构造逻辑，区分普通分析、项目修改规划、单文件改写和修复等模式
- `backend/structured_response.py`
  - 解析大模型输出的结构化动作与单文件改写结果
- `backend/request_classifier.py`
  - 识别当前请求是普通问答还是项目级修改
- `backend/agent_workflow.py`
  - 轻量工作流编排层，统一组织检索、规划和动作校验
- `backend/tools/current_file_tool.py`
  - 当前文件分析工具
- `backend/tools/workspace_search_tool.py`
  - 工作区文件检索工具
- `backend/tools/workspace_plan_tool.py`
  - 当模型结构化输出不稳定时，先用规则选出最值得修改的目标文件
- `backend/tools/workspace_action_tool.py`
  - 多文件动作的校验、文档安全检查与补全过程
- `backend/tools/demo_action_tool.py`
  - 为示例文件提供演示保底动作，避免弱模型导致整条演示链路中断
- `backend/ollama_client.py`
  - Python 后端与 Ollama 的通信封装，并默认使用低随机性参数提升结构化输出稳定性

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
- `webview-src/types.ts`
  - Webview 消息与展示类型定义
- `webview-src/vscode.ts`
  - Webview 侧对 VS Code API 的封装
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
4. 后端优先尝试让模型直接返回结构化动作；如果失败，会退回逐文件生成与修复流程。
5. 插件将建议渲染为 diff 预览，等待用户确认。
6. 用户确认后，插件端执行文件创建、更新或文档修改。

## 本地运行

1. 启动 Python 后端（请确认已创建 Conda 环境，且 Python 版本为 3.10）

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
- 核心源码统一采用较正式的中文文件说明与函数说明注释，函数说明放置于函数定义上方
- 每次调整目录结构或新增关键文件后，需要同步更新本 `README.md`
- 提交信息建议遵循 Conventional Commits，例如 `feat:`、`fix:`、`docs:`、`chore:`

## 适合演示的示例请求

- `请分析当前文件的作用、关键结构、潜在问题，并给出可执行的改进建议。`
- `请先检索当前项目相关文件，再规划一组待确认的项目级修改方案。`
- `请为当前项目生成一组待确认的文档更新方案，优先考虑 README.md 和 docs 目录。`
