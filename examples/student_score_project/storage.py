"""
数据存取逻辑。

本文件负责读取和写入学生成绩 JSON 文件。
当前实现故意保持为较直接的写法，便于后续演示存储层重构与异常处理优化。
"""

import json
from pathlib import Path

try:
    from student_score_project.models import StudentRecord
except ModuleNotFoundError:
    from models import StudentRecord


class StudentStorage:
    """
    封装学生成绩数据的文件读写行为。
    """

    def load(self, file_path: str | Path) -> list[StudentRecord]:
        """
        从 JSON 文件中读取学生成绩列表。
        """

        target_path = Path(file_path)
        if not target_path.exists():
            return []

        with target_path.open("r", encoding="utf-8") as file:
            raw_items = json.load(file)

        students: list[StudentRecord] = []
        for item in raw_items:
            students.append(StudentRecord.from_dict(item))

        return students

    def save(self, file_path: str | Path, students: list[StudentRecord]) -> None:
        """
        将学生成绩列表写回 JSON 文件。
        """

        target_path = Path(file_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)

        serialized: list[dict[str, int | str]] = []
        for student in students:
            serialized.append(student.to_dict())

        with target_path.open("w", encoding="utf-8") as file:
            json.dump(serialized, file, ensure_ascii=False, indent=2)
