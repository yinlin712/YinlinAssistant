"""
报表生成逻辑。

本文件负责计算成绩等级，并输出适合终端展示的成绩报告。
当前实现保留了一些重复计算与字符串拼接逻辑，便于演示后续重构空间。
"""

try:
    from student_score_project.models import StudentRecord
except ModuleNotFoundError:
    from models import StudentRecord


def build_level(average_score: float) -> str:
    """
    根据平均分计算等级。
    """

    if average_score >= 90:
        return "A"
    if average_score >= 80:
        return "B"
    if average_score >= 70:
        return "C"
    return "D"


def format_student_line(student: StudentRecord) -> str:
    """
    将单个学生对象格式化为一行报告文本。
    """

    average_score = (student.math + student.english + student.python) / 3
    level = build_level(average_score)
    return " | ".join(
        [
            f"姓名: {student.name}",
            f"数学: {student.math}",
            f"英语: {student.english}",
            f"Python: {student.python}",
            f"平均分: {average_score:.2f}",
            f"等级: {level}",
        ]
    )


def build_report_lines(students: list[StudentRecord]) -> list[str]:
    """
    将学生列表转换为报表行文本。
    """

    report_lines: list[str] = []
    for student in students:
        report_lines.append(format_student_line(student))
    return report_lines


def build_full_report(students: list[StudentRecord], class_average: float) -> str:
    """
    生成完整的多行成绩报告文本。
    """

    body = "\n".join(f"[{line}]" for line in build_report_lines(students))
    return (
        "学生成绩报告\n"
        + "=" * 40
        + "\n"
        + body
        + "\n"
        + "=" * 40
        + f"\n全班平均分: {class_average:.2f}"
    )
