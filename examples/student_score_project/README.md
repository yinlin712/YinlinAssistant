# student_score_project

这是一个用于演示多文件协作与项目级改造能力的 Python 示例工程。

该目录应始终保持为“可运行的演示基线”。日常调试可以分析、生成方案和预览 diff，但不要将临时验证结果直接覆盖到这套样例代码中。

## 目录说明

- `main.py`
  - 演示入口，负责组装管理器并输出结果
- `manager.py`
  - 业务编排层，负责协调数据读取、统计和报表生成
- `models.py`
  - 数据模型定义
- `storage.py`
  - JSON 文件读写逻辑
- `report.py`
  - 报表拼装与等级计算逻辑
- `sample_data.json`
  - 示例输入数据

## 当前故意保留的改进点

- `main.py`
  - 仍然包含硬编码样本数据、重复追加数据和固定路径拼装逻辑
- `manager.py`
  - 同时承担数据管理、查找和报表触发职责，边界还不够清晰
- `models.py`
  - 同时保留 `avg` 属性和 `average_score()` 方法，接口不够统一
- `storage.py`
  - 缺少更明确的异常处理与数据校验
- `report.py`
  - 仍有重复的平均分计算与字符串拼接逻辑

## 运行方式

```powershell
python examples/student_score_project/main.py
```
