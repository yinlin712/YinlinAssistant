from pathlib import Path

from backend.models import AgentContextModel
from backend.structured_response import ParsedAction

# 文件说明：
# 本文件提供“演示保底动作”。
# 当本地模型能力不足以稳定生成可执行动作时，示例文件仍可借助这里的规则化方案完成演示。

DEMO_SAMPLE_FILE_NAME = "sample_student_manager.py"


# 类说明：
# 为示例文件构造稳定、可执行的本地保底动作。
class DemoActionTool:
    # 方法说明：
    # 仅在当前活动文件是演示样例时返回保底动作。
    def build_demo_actions(self, context: AgentContextModel) -> list[ParsedAction]:
        if not context.activeFile or not context.workspaceRoot:
            return []

        active_path = Path(context.activeFile)
        if active_path.name != DEMO_SAMPLE_FILE_NAME:
            return []

        try:
            relative_path = str(active_path.resolve().relative_to(Path(context.workspaceRoot).resolve())).replace("\\", "/")
        except ValueError:
            return []

        return [
            ParsedAction(
                kind="update_file",
                target_file=relative_path,
                summary="演示保底方案：优化示例文件的结构与异常处理",
                updated_content=self._build_demo_sample_content(),
            )
        ]

    # 方法说明：
    # 返回演示样例文件的保底重构版本。
    def _build_demo_sample_content(self) -> str:
        return '''"""
这是一个专门给 Vibe Coding Agent 演示用的样例文件。

它故意保留了一些“可以优化”的地方，方便你测试：
1. 结构分析
2. 代码解释
3. 重构建议
4. 初学者友好的讲解能力
"""

import json


class StudentScoreManager:
    def __init__(self):
        self.students = []

    def load_students(self, file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as file:
                content = file.read()
                self.students = json.loads(content)
        except FileNotFoundError:
            print(f"未找到学生数据文件：{file_path}")
            self.students = []
        except json.JSONDecodeError as error:
            print(f"学生数据格式错误：{error}")
            self.students = []
        except OSError as error:
            print(f"读取学生数据失败：{error}")
            self.students = []

    def add_student(self, name, math, english, python_score):
        student = {
            "name": name,
            "math": math,
            "english": english,
            "python": python_score,
        }
        self.students.append(student)

    def calculate_average_score(self):
        total_score = 0
        subject_count = 0

        for student in self.students:
            total_score += student["math"]
            total_score += student["english"]
            total_score += student["python"]
            subject_count += 3

        if subject_count == 0:
            return 0

        return total_score / subject_count

    def build_report_lines(self):
        report_lines = []

        for student in self.students:
            average = self._calculate_student_average(student)
            level = self._calculate_student_level(average)
            report_lines.append(self._format_student_line(student, average, level))

        return report_lines

    def print_report(self):
        print("学生成绩报告")
        print("=" * 40)

        for line in self.build_report_lines():
            print(f"[{line}]")

        print("=" * 40)
        print(f"全班平均分: {self.calculate_average_score():.2f}")

    def _calculate_student_average(self, student):
        total_score = student["math"] + student["english"] + student["python"]
        return total_score / 3

    def _calculate_student_level(self, average):
        if average >= 90:
            return "A"
        if average >= 80:
            return "B"
        if average >= 70:
            return "C"
        return "D"

    def _format_student_line(self, student, average, level):
        return (
            f"姓名: {student['name']} | "
            f"数学: {student['math']} | "
            f"英语: {student['english']} | "
            f"Python: {student['python']} | "
            f"平均分: {average:.2f} | "
            f"等级: {level}"
        )


def run_demo():
    manager = StudentScoreManager()

    manager.load_students("sample_data.json")
    manager.add_student("李博由", 95, 88, 93)
    manager.add_student("陈裕森", 76, 81, 70)
    manager.add_student("苗好田", 66, 72, 79)

    manager.print_report()


if __name__ == "__main__":
    run_demo()
'''
