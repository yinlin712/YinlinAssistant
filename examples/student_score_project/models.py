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

    def __post_init__(self):
        """
        初始化后处理，确保所有成绩在有效范围内。
        """

        for subject in ["math", "english", "python"]:
            if not (0 <= getattr(self, subject) <= 100):
                setattr(self, subject, 0)
