"""
示例工程入口。

本文件负责组装演示用的学生成绩管理器，并输出最终报告。
当前实现保持可运行，但仍保留了一些适合做项目级重构的改进点。
"""

from pathlib import Path

try:
    from student_score_project.manager import StudentScoreManager
except ModuleNotFoundError:
    from manager import StudentScoreManager


def build_demo_manager() -> StudentScoreManager:
    """
    构造演示用管理器，并写入一部分硬编码数据。
    """

    manager = StudentScoreManager()
    data_file = Path(__file__).with_name("sample_data.json")

    manager.load_students(data_file)
    manager.add_student("李博由", 95, 88, 93)
    manager.add_student("陈裕森", 76, 81, 70)
    manager.add_student("苗好田", 66, 72, 79)
    return manager


def run_demo() -> None:
    """
    运行学生成绩演示流程。
    """

    manager = build_demo_manager()
    print(manager.generate_report())


if __name__ == "__main__":
    run_demo()
