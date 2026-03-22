"""
这是一个供 Vibe Coding Agent 演示使用的样例文件。

文件中故意保留了若干可以优化的实现方式，便于演示：
1. 结构分析
2. 代码解释
3. 重构建议
4. 项目级修改预览
"""

import json


# 类说明：
# 管理学生成绩数据，并生成用于展示的成绩报告。
class StudentScoreManager:
    # 方法说明：
    # 初始化学生列表。
    def __init__(self):
        self.students = []

    # 方法说明：
    # 从 JSON 文件中加载学生成绩数据。
    def load_students(self, file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as file:
                content = file.read()
                self.students = json.loads(content)
        except Exception as error:
            print(f"读取学生数据失败：{error}")
            self.students = []

    # 方法说明：
    # 向当前列表追加一条学生成绩记录。
    def add_student(self, name, math, english, python_score):
        student = {
            "name": name,
            "math": math,
            "english": english,
            "python": python_score,
        }
        self.students.append(student)

    # 方法说明：
    # 计算全班三门课程的平均分。
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

    # 方法说明：
    # 为每名学生生成一行可打印的成绩报告文本。
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

    # 方法说明：
    # 打印完整的学生成绩报告。
    def print_report(self):
        print("学生成绩报告")
        print("=" * 40)

        for line in self.build_report_lines():
            print(f"[{line}]")

        print("=" * 40)
        print("全班平均分:", self.calculate_average_score())


# 函数说明：
# 构造一组示例数据并打印报告，便于演示插件行为。
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
