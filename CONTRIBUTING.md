# 贡献指南

感谢你关注 YinlinAssistant。

这个项目同时承担两个目标：
- 作为毕业设计的持续演进项目
- 作为一个结构清晰、适合继续扩展的开源编程助手原型

为了让协作过程稳定、可维护、对初学者友好，请在提交前先阅读本文件。

## 开始之前

1. 先阅读 [README.md](./README.md)，了解整体目录和运行方式。
2. 如果你要修改系统设计或边界，请同步阅读 [docs/architecture.md](./docs/architecture.md) 和 [docs/project-boundary.md](./docs/project-boundary.md)。
3. 如果你的改动涉及目录结构、关键模块职责或新的开发流程，请同步更新根目录的 [README.md](./README.md)。

## 本地开发环境

推荐使用仓库约定的 Conda 环境：

```powershell
conda env create -f environment.yml
conda activate CodingAgent
```

后端依赖也可以通过下面命令补装：

```powershell
pip install -r requirements.txt
```

前端与插件端依赖安装：

```powershell
npm install
```

## 启动方式

启动 Python 后端：

```powershell
& 'E:\ANACONDA\condabin\conda.bat' run -n CodingAgent python -m uvicorn backend.main:app --reload
```

构建插件与 Webview：

```powershell
npm run build
```

启动 VS Code 插件开发宿主：

1. 用 VS Code 打开仓库根目录
2. 按 `F5`
3. 在新的开发宿主窗口中测试插件

## 代码组织约定

- `backend/`
  - 放 Python Agent 核心逻辑、工具调用、提示词构造、模型接入
- `src/`
  - 放 VS Code 插件壳层逻辑，例如命令注册、上下文采集、文件应用
- `webview-src/`
  - 放 Vue Webview 前端界面
- `docs/`
  - 放架构说明和论文支撑文档

请尽量保持这几个边界清晰，不要把后端逻辑直接塞进插件壳层。

## 编码建议

- 变量和函数命名尽量直观，优先让初学者也能读懂
- 中文注释要解释“为什么这样做”，而不是简单翻译代码
- Python 是后端首选语言，非必要不要把后端逻辑迁移到 TypeScript
- Webview UI 优先维护 Vue 组件，不继续扩展纯手写 DOM 方案
- 涉及文件写回和项目级修改时，请优先保证安全性和可回退性

## 提交规范

建议使用 Conventional Commits：

- `feat:` 新功能
- `fix:` 缺陷修复
- `docs:` 文档更新
- `refactor:` 重构
- `test:` 测试相关
- `chore:` 工程化、依赖、配置调整

示例：

```text
feat: support project-level diff preview
docs: update README for open source structure
fix: repair malformed structured action parsing
```

## Pull Request 建议

提交 PR 时，建议包含以下内容：

- 改动目标是什么
- 为什么要这样改
- 是否影响插件端、后端、Webview 或文档
- 你做了哪些本地验证
- 是否同步更新了 README 和相关文档

## 合并前自检

在发起 PR 前，建议至少完成下面检查：

```powershell
npm run build
python -m compileall backend
```

如果你的改动引入了新的脚本、命令、目录或配置，请把对应说明补到 README。
