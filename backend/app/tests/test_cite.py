import re
import os
import json


def split_footnotes(text: str) -> tuple[str, list[tuple[str, str]]]:
    """分离正文和脚注定义"""
    main_text = re.sub(
        r"\n\[\^\d+\]:.*?(?=\n\[\^|\n\n|\Z)", "", text, flags=re.DOTALL
    ).strip()

    # 匹配脚注定义
    footnotes = re.findall(r"\[\^(\d+)\]:\s*(.+?)(?=\n\[\^|\n\n|\Z)", text, re.DOTALL)
    return main_text, footnotes


def extract_footnote_references(text: str) -> list[tuple[str, str]]:
    """提取文本中的脚注引用和对应的脚注内容"""
    # 匹配脚注引用模式：[^数字]: 内容（处理多种可能的结束方式）
    # 支持以句号、换行或文本结尾结束的脚注
    pattern = r"\[\^(\d+)\]:\s*([^[\n]+?)(?=\[\^|\n\n|\n-|\n\d+\.|\n\*|$)"
    matches = re.findall(pattern, text, re.DOTALL)

    # 清理匹配结果
    cleaned_matches = []
    for num, content in matches:
        # 移除末尾的句号和多余空白
        content = content.strip()
        if content.endswith("。"):
            content = content[:-1]
        if content.endswith("."):
            content = content[:-1]
        cleaned_matches.append((num, content))

    return cleaned_matches


class UserOutput:
    def __init__(self):
        self.res: dict[str, dict] = {}
        self.cost_time = 0.0
        self.initialized = True

    def get_result_to_save(self, ques_count):
        # 保存 res.json 文件

        # 动态顺序获取拼接res value，正确拼接顺序
        ques_str = [f"ques{i}" for i in range(1, ques_count + 1)]

        # 修改：调整章节顺序，确保符合论文结构
        seq = [
            "firstPage",  # 标题、摘要、关键词
            "RepeatQues",  # 一、问题重述
            "analysisQues",  # 二、问题分析
            "modelAssumption",  # 三、模型假设
            "symbol",  # 四、符号说明和数据预处理
            "eda",  # 四、数据预处理（EDA部分）
            *ques_str,  # 五、模型的建立与求解（问题1、2...）
            "sensitivity_analysis",  # 六、模型的分析与检验
            "judge",  # 七、模型的评价、改进与推广
        ]

        # 全局文献列表，用于去重和统一编号
        global_footnotes = []  # 存储所有唯一的文献内容
        footnote_content_to_id = {}  # 文献内容到全局ID的映射

        # 处理后的各节内容
        processed_sections = []

        for key in seq:
            if key not in self.res:
                continue

            content = self.res[key]["response_content"]
            print(f"\n处理节: {key}")

            # 1. 提取当前节的文献引用
            current_footnotes = extract_footnote_references(content)
            print(f"当前节文献: {current_footnotes}")

            # 2. 处理每个文献引用
            section_footnote_mapping = {}  # 当前节内的旧编号到新编号映射

            for old_num, footnote_content in current_footnotes:
                # 清理文献内容
                footnote_content = footnote_content.strip()
                if footnote_content.endswith("。"):
                    footnote_content = footnote_content[:-1]

                # 3. 检查是否已存在于全局列表
                if footnote_content in footnote_content_to_id:
                    # 文献已存在，使用已有的全局编号
                    global_id = footnote_content_to_id[footnote_content]
                    print(f"文献已存在: {footnote_content} -> 使用编号 {global_id}")
                else:
                    # 新文献，添加到全局列表
                    global_footnotes.append(footnote_content)
                    global_id = len(global_footnotes)
                    footnote_content_to_id[footnote_content] = global_id
                    print(f"新文献: {footnote_content} -> 分配编号 {global_id}")

                section_footnote_mapping[old_num] = global_id

            # 4. 更新当前节中的脚注引用编号
            processed_content = content

            # 更新引用编号
            for old_num, new_num in section_footnote_mapping.items():
                # 替换文中的引用，但不处理脚注定义
                processed_content = re.sub(
                    rf"\[\^{old_num}\](?!:)", f"[^{new_num}]", processed_content
                )

            # 移除原有的脚注定义（以换行开头的完整定义行）
            processed_content = re.sub(
                r"\n\[\^\d+\]:\s*[^[\n]+?(?=\n\[\^|\n\n|\n-|\n\d+\.|\n\*|$)",
                "",
                processed_content,
                flags=re.DOTALL,
            ).strip()

            processed_sections.append(processed_content)
            print("processed_sections:", processed_sections)
            print(f"节 {key} 脚注映射: {section_footnote_mapping}")

        # 5. 合并所有处理后的内容
        full_content = "\n\n".join(processed_sections)

        # 6. 添加重新编号后的脚注到文档末尾
        if global_footnotes:
            full_content += "\n\n## 参考文献\n\n"
            for i, footnote_content in enumerate(global_footnotes, 1):
                full_content += f"[^{i}]: {footnote_content}\n\n"

        print(f"\n最终全局文献列表: {global_footnotes}")
        return full_content


if __name__ == "__main__":
    with open("res.json", "r", encoding="utf-8") as f:
        res = json.load(f)
    user_output = UserOutput()
    user_output.res = res

    with open("res.md", "w", encoding="utf-8") as f:
        f.write(user_output.get_result_to_save(ques_count=1))
