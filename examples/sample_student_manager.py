"""
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
        except Exception as error:
            print(f"读取学生数据失败：{error}")
            self.students = []

    def add_student(self, name, math, english, python_score):
        student = {
            "name": name,
            "math": math,
            "english": english,
            "python": python_score
        }
        self.students.append(student)

    def calculate_average_score(self):
        total = 0
        count = 0

        for student in self.students:
            total += student["math"]
            count += 1
            total += student["english"]
            count += 1
            total += student["python"]
            count += 1

        if count == 0:
            return 0

        return total / count

    def build_report_lines(self):
        report_lines = []

        for student in self.students:
            average = (student["math"] + student["english"] + student["python"]) / 3

            if average >= 90:
                level = "A"
            elif average >= 80:
                level = "B"
            elif average >= 70:
                level = "C"
            else:
                level = "D"

            line = (
                f"姓名: {student['name']} | "
                f"数学: {student['math']} | "
                f"英语: {student['english']} | "
                f"Python: {student['python']} | "
                f"平均分: {average:.2f} | "
                f"等级: {level}"
            )
            report_lines.append(line)

        return report_lines

    def print_report(self):
        print("学生成绩报告")
        print("=" * 40)

        for line in self.build_report_lines():
            print(f"[{line}]")

        print("=" * 40)
        print("全班平均分:", self.calculate_average_score())


def run_demo():
    manager = StudentScoreManager()

    try:
        manager.load_students("sample_data.json")
    except Exception as error:
        print(f"错误：无法加载数据 {error}")

    manager.add_student("李博由", 95, 88, 93)
    manager.add_student("陈裕森", 76, 81, 70)
    manager.add_student("苗好田", 66, 72, 79)

    manager.print_report()


if __name__ == "__main__":
    run_demo()
