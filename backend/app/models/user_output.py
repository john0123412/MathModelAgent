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

        # 收集所有内容
        all_content = []
        for key in seq:
            if key not in self.res:
                logger.debug(f"跳过不存在的键: {key}")
                continue
            content = self.res[key]["response_content"]
            all_content.append(content)

        # 合并所有内容
        full_content = "\n".join(all_content)

        # 提取所有脚注引用 [^1], [^2] 等
        footnote_refs = re.findall(r"\[\^(\d+)\]", full_content)

        # 提取所有脚注定义 [^1]: 内容
        footnote_defs = re.findall(
            r"\[\^(\d+)\]:\s*(.+?)(?=\n\[\^|\n\n|\Z)", full_content, re.DOTALL
        )

        logger.info(f"找到脚注引用: {set(footnote_refs)}")
        logger.info(f"找到脚注定义: {[def_num for def_num, _ in footnote_defs]}")

        # 创建脚注映射和内容
        footnote_mapping = {}
        footnote_contents = {}
        footnote_counter = 1

        # 收集所有唯一的脚注编号（来自引用和定义）
        all_footnote_nums = set(footnote_refs)
        for def_num, def_content in footnote_defs:
            all_footnote_nums.add(def_num)
            footnote_contents[def_num] = def_content.strip()

        # 为每个脚注分配新编号
        for old_num in sorted(all_footnote_nums, key=int):
            footnote_mapping[old_num] = str(footnote_counter)
            footnote_counter += 1

        logger.info(f"脚注映射: {footnote_mapping}")

        # 更新正文中的脚注引用编号
        processed_content = full_content
        for old_num, new_num in footnote_mapping.items():
            processed_content = processed_content.replace(
                f"[^{old_num}]", f"[^{new_num}]"
            )

        # 移除原有的脚注定义（它们会被重新添加到最后）
        processed_content = re.sub(
            r"\[\^\d+\]:\s*.+?(?=\n\[\^|\n\n|\Z)",
            "",
            processed_content,
            flags=re.DOTALL,
        )

        # 清理多余的空行
        processed_content = re.sub(r"\n{3,}", "\n\n", processed_content)

        # 添加统一的参考文献部分
        if footnote_mapping:
            processed_content += "\n\n## 参考文献\n\n"

            # 按新编号顺序添加脚注
            for old_num in sorted(
                footnote_mapping.keys(), key=lambda x: int(footnote_mapping[x])
            ):
                new_num = footnote_mapping[old_num]
                if old_num in footnote_contents:
                    processed_content += f"[^{new_num}]: {footnote_contents[old_num]}\n"
                else:
                    logger.warning(f"脚注 {old_num} 被引用但未找到定义")

            logger.info(f"参考文献部分添加完成，共有 {len(footnote_mapping)} 个脚注")

        logger.info(f"结果处理完成，最终内容长度: {len(processed_content)}")
        return processed_content

    def save_result(self, ques_count):
        res_path = os.path.join(self.work_dir, "res.md")
        with open(res_path, "w", encoding="utf-8") as f:
            f.write(self.get_result_to_save(ques_count))
