"""
业务编排逻辑。

本文件负责协调数据存取与报表生成，是示例工程的业务层入口。
当前实现保持可运行，同时故意保留了若干可优化点，便于演示项目级多文件改造。
"""

from pathlib import Path

try:
    from student_score_project.models import StudentRecord
    from student_score_project.report import build_full_report
    from student_score_project.storage import StudentStorage
except ModuleNotFoundError:
    from models import StudentRecord
    from report import build_full_report
    from storage import StudentStorage


class StudentScoreManager:
    """
    管理学生成绩数据，并提供统计与报表能力。
    """

    def __init__(self, storage: StudentStorage | None = None) -> None:
        """
        初始化管理器，并允许注入自定义存储实现。
        """

        self.storage = storage or StudentStorage()
        self._students: list[StudentRecord] = []

    @property
    def students(self) -> list[StudentRecord]:
        """
        暴露当前学生列表。
        """

        return self._students

    def load_students(self, file_path: str | Path) -> None:
        """
        读取外部文件中的学生成绩数据。
        """

        self._students = self.storage.load(file_path)

    def save_students(self, file_path: str | Path) -> None:
        """
        将当前成绩数据写回指定文件。
        """

        self.storage.save(file_path, self._students)

    def add_student(self, name: str, math: int, english: int, python_score: int) -> None:
        """
        新增一条学生成绩记录。
        """

        self._students.append(
            StudentRecord(
                name=name,
                math=math,
                english=english,
                python=python_score,
            )
        )

    def add_students(self, students: list[dict[str, int | str]]) -> None:
        """
        批量新增学生记录。
        """

        for item in students:
            self._students.append(StudentRecord.from_dict(item))

    def calculate_average_score(self) -> float:
        """
        计算全班平均分。
        """

        if not self._students:
            return 0.0

        total_score = 0.0
        count = 0
        for student in self._students:
            total_score += student.average_score()
            count += 1

        if count == 0:
            return 0.0

        return total_score / count

    def find_student(self, name: str) -> StudentRecord | None:
        """
        根据姓名查找学生记录。
        """

        for student in self._students:
            if student.name == name:
                return student
        return None

    def generate_report(self) -> str:
        """
        生成完整的成绩报告文本。
        """

        try:
            average_score = self.calculate_average_score()
            return build_full_report(self._students, average_score)
        except ValueError as error:
            print(f"生成报告时出现数值错误: {error}")
            return ""
        except Exception as error:
            print(f"生成报告时出现未知错误: {error}")
            return ""
