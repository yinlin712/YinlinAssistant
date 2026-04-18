"""
数据模型定义。

本文件定义学生成绩对象，并提供基础的数据转换能力。
当前同时保留了属性和方法两种平均分入口，便于后续演示统一接口的重构需求。
"""

from dataclasses import dataclass


@dataclass
class StudentRecord:
    """
    表示单个学生的成绩记录。
    """

    name: str
    math: int
    english: int
    python: int

    @property
    def avg(self) -> float:
        """
        以属性形式返回平均分。
        """

        return self.average_score()

    def average_score(self) -> float:
        """
        以方法形式返回平均分。
        """

        return (self.math + self.english + self.python) / 3

    def to_dict(self) -> dict[str, int | str]:
        """
        将对象转换为可序列化字典。
        """

        return {
            "name": self.name,
            "math": self.math,
            "english": self.english,
            "python": self.python,
        }

    @classmethod
    def from_dict(cls, raw_data: dict[str, int | str]) -> "StudentRecord":
        """
        从字典结构构造学生记录。
        """

        python_score = raw_data.get("python", raw_data.get("python_score", 0))
        return cls(
            name=str(raw_data.get("name", "")),
            math=int(raw_data.get("math", 0)),
            english=int(raw_data.get("english", 0)),
            python=int(python_score),
        )
