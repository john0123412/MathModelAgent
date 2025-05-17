import os
from app.utils.data_recorder import DataRecorder
from app.models.model import WriterResponse


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
            "reference",
        ]

        # 收集所有内容和脚注
        all_content = []
        all_footnotes = []
        footnote_counter = 1

        for key in seq:
            if key not in self.res:
                continue

            content = self.res[key]["response_content"]
            footnotes = self.res[key]["footnotes"]

            # 更新内容中的脚注引用编号
            if footnotes:
                # 获取当前内容中的所有脚注引用
                current_footnotes = footnotes.split("\n")

                # 更新内容中的脚注引用编号
                for i, _ in enumerate(current_footnotes, start=footnote_counter):
                    content = content.replace(
                        f"[^{i - footnote_counter + 1}]", f"[^{i}]"
                    )

                # 更新脚注编号
                updated_footnotes = []
                for i, footnote in enumerate(current_footnotes, start=footnote_counter):
                    updated_footnote = footnote.replace(
                        f"[^{i - footnote_counter + 1}]:", f"[^{i}]:"
                    )
                    updated_footnotes.append(updated_footnote)

                footnote_counter += len(current_footnotes)
                all_footnotes.extend(updated_footnotes)

            all_content.append(content)

        # 合并所有内容和脚注
        final_content = "\n".join(all_content)
        if all_footnotes:
            final_content += "\n\n" + "\n".join(all_footnotes)

        return final_content

    def save_result(self, ques_count):
        res_path = os.path.join(self.work_dir, "res.md")
        with open(res_path, "w", encoding="utf-8") as f:
            f.write(self.get_result_to_save(ques_count))
