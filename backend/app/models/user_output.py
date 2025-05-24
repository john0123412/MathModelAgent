import os
import re
from app.utils.data_recorder import DataRecorder
from app.schemas.A2A import WriterResponse
from app.utils.log_util import logger


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
        logger.info(f"开始处理结果保存，问题数量: {ques_count}")
        # 动态顺序获取拼接res value，正确拼接顺序
        ques_str = [f"ques{i}" for i in range(1, ques_count + 1)]
        seq = [
            "firstPage",
            "RepeatQues",
            "analysisQues",
            "modelAssumption",
            "symbol",
            "eda",
            *ques_str,
            "sensitivity_analysis",
            "judge",
        ]
        logger.debug(f"处理序列: {seq}")

        # 收集所有内容和脚注
        all_content = []
        all_footnotes = []
        footnote_counter = 1
        footnote_mapping = {}  # 用于存储原始编号到新编号的映射

        # 第一遍：收集所有引用并建立映射
        logger.info("开始第一遍处理：收集引用并建立映射")
        for key in seq:
            if key not in self.res:
                logger.debug(f"跳过不存在的键: {key}")
                continue

            content = self.res[key]["response_content"]
            footnotes = self.res[key]["footnotes"]

            if footnotes:
                logger.debug(f"处理 {key} 的脚注，数量: {len(footnotes)}")
                for num, content in footnotes:  # 直接解构元组
                    if num not in footnote_mapping:
                        footnote_mapping[num] = str(footnote_counter)
                        footnote_counter += 1

        logger.info(f"脚注映射完成，共有 {len(footnote_mapping)} 个脚注")

        # 第二遍：更新内容和脚注
        logger.info("开始第二遍处理：更新内容和脚注")
        for key in seq:
            if key not in self.res:
                continue

            content = self.res[key]["response_content"]
            footnotes = self.res[key]["footnotes"]

            # 更新内容中的引用编号
            if footnotes:
                logger.debug(f"更新 {key} 的内容和脚注")
                # 更新正文中的引用
                for old_num, new_num in footnote_mapping.items():
                    content = content.replace(f"[^{old_num}]", f"[^{new_num}]")

                # 更新脚注
                updated_footnotes = []
                for num, content in footnotes:  # 直接解构元组
                    new_num = footnote_mapping[num]
                    updated_footnote = f"[^{new_num}]: {content.strip()}"
                    updated_footnotes.append(updated_footnote)

                all_footnotes.extend(updated_footnotes)

            all_content.append(content)

        # 合并所有内容和脚注
        final_content = "\n".join(all_content)
        if all_footnotes:
            # 对脚注按编号排序
            sorted_footnotes = sorted(
                all_footnotes, key=lambda x: int(re.search(r"\[\^(\d+)\]:", x).group(1))
            )
            final_content += "\n\n" + "\n".join(sorted_footnotes)

        logger.info(f"结果处理完成，最终内容长度: {len(final_content)}")
        return final_content

    def save_result(self, ques_count):
        res_path = os.path.join(self.work_dir, "res.md")
        with open(res_path, "w", encoding="utf-8") as f:
            f.write(self.get_result_to_save(ques_count))
