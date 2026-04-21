# YinlinAssistant

YinlinAssistant 是毕业设计《基于 Vibe Coding 的编程助手 Agent 研究与设计》的实现仓库。

项目采用“VS Code 插件 + Python 后端 + 本地大模型 + 数字人前端”的分层结构，目标不是做一个只能聊天的侧边栏，而是做一个能理解工程上下文、规划修改、预览 diff、确认写回，并具备数字人表达能力的编程助手原型。

## 当前架构

```text
VS Code 插件
├─ 采集当前编辑器 / 工作区上下文
├─ 展示聊天、diff 预览与文件应用结果
└─ 承接 Webview 数字人界面

Python 后端
├─ 请求分类
├─ Prompt 组织
├─ 工具编排
└─ 调用本地 Ollama 模型

数字人运行时
├─ VRM 预设清单
├─ 状态桥接与前端协议
├─ Webview 配置解析
└─ 后续动作 / 表情 / TTS / API 扩展入口
```

## 目录结构

```text
.
├─ .github/                 GitHub 协作模板与仓库配置
├─ .vscode/                 调试与任务配置
├─ backend/                 Python 后端与 Agent 编排
├─ config/                  模型档案配置
├─ data/                    LoRA 训练与评估数据目录
├─ docs/                    架构与论文相关文档
├─ examples/                演示样例工程
├─ media/                   Webview 打包产物与样式
├─ models/                  LoRA 适配器与 Modelfile 目录
├─ src/                     VS Code 插件源码
├─ virtual/                 数字人运行时目录
├─ webview-src/             Vue Webview 源码
├─ environment.yml          Conda 环境定义
├─ package.json             插件清单与前端构建配置
├─ requirements.txt         Python 依赖
└─ README.md
```

## 关键目录说明

### `backend/`

- `backend/main.py`
  - FastAPI 入口，提供健康检查、普通生成和流式生成接口。
- `backend/service.py`
  - 后端主服务，负责编排问答、当前文件改写和项目级多文件方案。
- `backend/request_classifier.py`
  - 判断请求属于普通问答、当前文件修改还是项目级修改。
- `backend/prompt_builder.py`
  - 维护不同任务场景下的提示词模板。
- `backend/tools/`
  - 放置当前文件分析、工作区检索、修改规划与动作校验工具。
- `backend/tools/workspace_semantic_tool.py`
  - 对候选文件执行轻量语义排序，为项目级修改提供相关文件证据。
- `backend/tools/action_risk_tool.py`
  - 对待确认文件动作做风险评分，为提案摘要和演示界面提供安全提示。

### `src/`

- `src/extension.ts`
  - 插件入口，注册侧边栏、命令和预览服务。
- `src/panels/assistantPanel.ts`
  - 连接 Webview、插件端 Agent 与文件应用流程。
- `src/core/agent.ts`
  - 采集上下文并与 Python 后端通信。
- `src/core/actionExecutor.ts`
  - 执行文件创建、更新等具体操作。
- `src/core/editorDiffPreview.ts`
  - 打开 VS Code 原生 diff 预览。

### `webview-src/`

- `webview-src/App.vue`
  - Webview 顶层入口，负责聊天层、输入层和数字人背景层编排。
- `webview-src/components/ChatList.vue`
  - 聊天消息列表，支持流式消息、历史滚动和侧边滑块。
- `webview-src/components/Composer.vue`
  - 输入框与待确认修改操作区。
- `webview-src/components/AvatarPanel.vue`
  - 数字人工具栏与预设切换入口。
- `webview-src/components/avatar/VirtualAvatarStage.vue`
  - VRM 舞台层，负责模型加载、表情、眨眼、欢迎语和拖拽交互。

### `virtual/`

`virtual/` 是本项目的数字人运行时目录，用来统一管理与数字人相关的逻辑和业务入口。

- `virtual/avatar-presets.json`
  - 数字人预设清单，定义角色名称与 VRM 地址。
- `virtual/client-config.ts`
  - 读取插件端注入到 Webview 的数字人配置。
- `virtual/protocol.ts`
  - 数字人状态桥使用的事件协议。
- `virtual/bridge.ts`
  - 将 Code Agent 的状态同步给数字人运行时。
- `virtual/api.ts`
  - 为后续角色元数据、TTS、表情驱动等接口预留入口。

当前插件端已经不再直接读取本地 `airi/` 仓库目录来驱动数字人业务逻辑。
如果需要更换角色，只需要修改 `virtual/avatar-presets.json` 或配置本地 `.vrm` 路径。

## 当前能力

- 普通问答与代码解释
- 当前文件直接改写
- 项目级多文件修改规划
- 工程级语义检索增强
- 多文件修改风险评分
- VS Code 原生 diff 预览
- 流式回答与流式 patch 预览
- Markdown 回答渲染
- 聊天状态持久化
- 聊天层采用轻量透明消息泡与顶部渐隐历史展示，更接近工作台式对话布局
- 数字人预设切换
- 数字人欢迎语、轻量表情、眨眼与待机动作
- 数字人拖拽模式
- 本地 Qwen 模型接入，保留 DeepSeek 兼容兜底
- LoRA 训练数据与适配器目录预留

## 机器学习增强能力

### 1. 工程级语义检索

当前版本已经在“工作区候选文件检索”之上增加了一层轻量语义检索。它的目标不是直接改代码，而是先回答一个更基础的问题：

`这次需求最应该参考项目里的哪些文件？`

当前实现原理如下：

- 先对用户请求、选中代码和候选文件内容做轻量文本表示。
- 再基于统计权重与相似度排序，找出最相关的文件。
- 对中文需求中的领域词再做一层别名扩展，例如“报表”“平均分”“数据加载”会映射到 `report`、`average`、`load`、`storage` 等代码词。
- 检索结果会继续送入 Prompt，并在最终提案摘要中展示“语义检索优先命中的文件”。

从机器学习原理上看，这一部分属于：

- **无监督方法**
  - 当前没有人工标注训练集，也没有“需求到目标文件”的标签。
  - 它依赖的是文本统计表示、特征扩展和相似度排序，本质更接近无监督文本表示与信息检索。
- **不是监督学习分类器**
  - 当前没有训练一个“输入需求，输出目标文件”的分类模型。
- **后续可以升级**
  - 现在的结构已经为后续接入本地 embedding 模型留好了位置，可以逐步替换为真正的向量检索。

### 2. 修改风险评分

当前版本在生成文件动作之后，会对每个动作以及整组方案做一次风险评估。它主要关注：

- 是否跨多个文件
- 是否跨多个目录
- 是否新增文件
- 是否修改了导入关系
- 是否可能影响函数、类或接口签名
- 改动规模是否过大

从机器学习原理上看，这一部分属于：

- **规则驱动 / 特征工程评分**
  - 当前版本不是监督学习，也不是无监督聚类。
  - 它使用人工设计的工程特征进行加权评分，本质上是一个安全约束模块。
- **不依赖训练数据**
  - 当前没有标注“高风险样本”和“低风险样本”来训练分类器。
- **后续可以升级为监督学习**
  - 如果后期积累了足够多的“修改动作 + 是否回滚 + 是否通过测试”的样本，就可以把它进一步升级成真正的监督式风险预测器。

### 3. 当前版本的组合方式

为了保证毕设原型可以稳定演示，当前项目采用的是：

- `无监督语义检索 + 规则风险评分 + 本地大模型生成`

这套组合的优点是：

- 不依赖额外标注数据
- 可以完全在本地运行
- 容易解释，适合论文和答辩展示
- 后续可以平滑升级到 embedding 检索、监督式风险预测和 LoRA 微调模型

## 模型与 LoRA

- 默认模型：`qwen2.5-coder:7b`
- 兼容兜底模型：`deepseek-r1:7b`
- 模型档案：`config/model_profiles.json`
- LoRA 训练数据目录：`data/lora/train/`
- LoRA 评估数据目录：`data/lora/eval/`
- LoRA 适配器目录：`models/lora/adapters/`
- Ollama Modelfile 目录：`models/lora/modelfiles/`

当前结构已经为“本地基础模型 + LoRA 微调适配器 + 插件端统一接入”做了预留，后续替换模型不需要重写插件主链路。

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

当前 Webview 前端使用 `Vue + Vite` 构建，输出文件为 `media/webview.js`。

### 4. 调试插件

- 在 VS Code 中按 `F5`
- 默认调试配置会打开 `examples/student_score_project/`
- 侧边栏入口名称为 `Code Agent`

### 5. 配置本地 VRM

如果需要使用你自己的本地 VRM 模型，可以在 VS Code 设置中配置：

```text
vibeCodingAgent.avatarMode = vrm
vibeCodingAgent.avatarVrmPath = D:\\path\\to\\your\\model.vrm
```

## 示例工程

- `examples/sample_student_manager.py`
  - 单文件演示样例，适合测试当前文件分析与直接改写。
- `examples/student_score_project/`
  - 多文件演示工程，适合测试项目级检索、修改规划与 diff 预览。

示例工程应保持为“可运行的基线状态”，不要把临时演示结果直接写回到样例目录。

## Code Agent 的实现创新

### 1. 从“聊天插件”升级为“可执行的编程 Agent”

本项目不是把大模型简单塞进 VS Code，而是打通了：

`理解请求 -> 检索上下文 -> 规划修改 -> 展示 diff -> 确认写回`

这让它从“给建议的聊天框”变成了“能参与工程修改流程的 Agent 原型”。

### 2. 插件端与 Python 后端分层明确

- 插件端负责编辑器上下文、界面交互、diff 展示和文件应用。
- Python 后端负责请求分类、Prompt 组织、工具编排和模型调用。

这样的分层更适合后续继续接入新模型、LoRA 适配器或更多工具。

### 3. 支持项目级多文件修改，而不只盯着当前文件

当前系统不仅能解释或修改当前活动文件，还能在工作区内检索相关文件并规划多文件修改方案。

这一点比普通补全插件更接近真正的工程协作 Agent。

### 4. 在 Agent 主链路中加入了机器学习增强层

本项目并没有把“机器学习内容”孤立成一个与主线无关的附加模块，而是把它放进了最核心的编程 Agent 工作流中：

- 先做工作区候选文件检索
- 再做语义相关性排序
- 再生成项目级修改方案
- 最后补充风险评分并进入 diff 预览与确认写回

这意味着机器学习增强能力不是装饰性的，而是真正参与了“找文件、定范围、控风险”这三个关键决策步骤。

### 5. 面向本地模型与 LoRA 的可替换结构

项目默认运行在本地 Ollama 上，并已兼容 Qwen 与 DeepSeek 两类模型。

同时通过 `config/`、`data/lora/`、`models/lora/` 这些目录，为后续 LoRA 微调与适配器接入留好了结构。

### 6. 将数字人界面引入编程助手，而不是静态头像

本项目把数字人作为运行时层接入到了 Webview 中，并且让它与编程助手状态联动：

- 欢迎语播报
- 状态表情
- 轻量口型和眨眼
- 拖拽交互
- 角色切换

这使插件具备了更强的展示辨识度，也更契合“具身化编程助手”的研究方向。

## 开发约定

- Python 负责后端 Agent 编排、Prompt 与工具逻辑。
- TypeScript 负责 VS Code 插件壳层、编辑器交互和 Webview 桥接。
- Vue 负责 Webview 前端界面。
- 数字人运行时相关代码统一收口到 `virtual/`。
- 调整目录结构或新增关键文件后，需要同步更新本 README。
- 提交信息遵循 Conventional Commits。
