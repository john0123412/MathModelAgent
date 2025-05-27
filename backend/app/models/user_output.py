import os
import re
from app.utils.data_recorder import DataRecorder
from app.schemas.A2A import WriterResponse
from app.utils.log_util import logger
from app.utils.common_utils import split_footnotes
import json


class UserOutput:
    def __init__(self, work_dir: str, data_recorder: DataRecorder | None = None):
        self.work_dir = work_dir
        self.res: dict[str, dict] = {
            # "eda": {
            #     "response_content": "",
            #     "footnotes": "",
            # },
            # "ques1": {
            #     "response_content": "",
            #     "footnotes": "",
            # },
        }
        self.data_recorder = data_recorder
        self.cost_time = 0.0
        self.initialized = True

    def set_res(self, key: str, writer_response: WriterResponse):
        self.res[key] = {
            "response_content": writer_response.response_content,
            "footnotes": writer_response.footnotes,
        }

    def get_res(self):
        return self.res

    def get_model_build_solve(self) -> str:
        """获取模型求解"""
        model_build_solve = ",".join(
            f"{key}-{value}"
            for key, value in self.res.items()
            if key.startswith("ques") and key != "ques_count"
        )

        return model_build_solve

    def get_result_to_save(self, ques_count):
        # 保存 res.json 文件

        logger.info(f"开始处理结果保存，问题数量: {ques_count}")

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

        # 用于存储所有脚注
        all_footnotes: dict[str, str] = {}
        # 收集所有内容和处理脚注
        all_content = []

        for key in seq:
            if key not in self.res:
                logger.debug(f"跳过不存在的键: {key}")
                continue

            content = self.res[key]["response_content"]
            # 分离正文和脚注
            main_text, footnotes = split_footnotes(content)
            # 存储脚注内容（去重）
            for _, note_content in footnotes:
                all_footnotes[note_content] = note_content
            all_content.append(main_text)

        # 合并所有内容
        full_content = "\n".join(all_content)

        # 重新编号脚注引用
        footnote_mapping = {}  # 旧编号到新编号的映射
        for i, content in enumerate(all_footnotes.values(), 1):
            footnote_mapping[content] = str(i)

        # 更新正文中的脚注引用
        for old_content, new_num in footnote_mapping.items():
            # 在正文中查找并替换脚注引用
            pattern = r"\[\^\d+\]"
            # 只替换一次，确保引用的一致性
            full_content = re.sub(pattern, f"[^{new_num}]", full_content, count=1)

        # 添加重新编号后的脚注到文档末尾
        if all_footnotes:
            full_content += "\n\n## 参考文献\n\n"
            for content, num in footnote_mapping.items():
                full_content += f"[^{num}]: {content}\n\n"

        return full_content

    def save_result(self, ques_count):
        with open(os.path.join(self.work_dir, "res.json"), "w", encoding="utf-8") as f:
            json.dump(self.res, f, ensure_ascii=False, indent=4)

        res_path = os.path.join(self.work_dir, "res.md")
        with open(res_path, "w", encoding="utf-8") as f:
            f.write(self.get_result_to_save(ques_count))
