"""工作流程定义模块，管理建模任务的求解和写作流程。"""

import logging
import re

from app.models.user_output import UserOutput
from app.tools.base_interpreter import BaseCodeInterpreter
from app.tools.paper_postprocessor import build_result_fact_summary
from app.tools.result_integrity import validate_result_freeze
from app.core.agents.modeler_agent import ModelerToCoder
from app.schemas.problem_contract import ProblemContract


_COMPUTED_NUMBER_RE = re.compile(r"(?<![A-Za-z_])[-+]?\d+(?:\.\d+)?(?![A-Za-z_])")
logger = logging.getLogger(__name__)


def _redact_computed_numbers(text: str) -> str:
    """Keep method context without leaking a second numerical baseline."""
    return _COMPUTED_NUMBER_RE.sub("[冻结数值]", text)


class Flows:
    """管理数学建模任务的求解流程和写作流程。"""
    def __init__(
        self,
        questions: dict[str, str | int],
        problem_contract: ProblemContract | None = None,
    ):
        self.flows: dict[str, dict] = {}
        self.questions: dict[str, str | int] = questions
        self.problem_contract = problem_contract

    def set_flows(self, ques_count: int):
        """根据问题数量设置流程节点。

        Args:
            ques_count: 问题数量。
        """
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
        self.flows = {key: {} for key in seq}

    def get_solution_flows(
        self, questions: dict[str, str | int], modeler_response: ModelerToCoder
    ):
        """生成求解阶段的流程配置。

        Args:
            questions: 包含各问题描述的字典。
            modeler_response: 建模手的响应，包含各问题的解决方案。

        Returns:
            求解流程配置字典，键为任务名，值包含 coder_prompt 等信息。
        """
        questions_quesx = {
            key: value
            for key, value in questions.items()
            if key.startswith("ques") and key != "ques_count"
        }
        solutions = modeler_response.questions_solution
        contract_prompt = self.problem_contract.to_prompt() if self.problem_contract else ""

        def plan_context(key: str) -> str:
            subtask_plan = modeler_response.get_subtask_plan(key)
            if subtask_plan:
                return (
                    "【建模手结构化交接（必须逐项落实，不得只写 PNG 或文字结论）】\n"
                    + subtask_plan.to_coder_summary()
                )
            return "参考建模手给出的解决方案：" + solutions.get(key, "")

        ques_flow = {
            key: {
                "coder_prompt": f"""
                        {contract_prompt}
                        不可变参数必须原样使用；如果建模手方案与题面参数契约冲突，以题面参数契约为准并在代码注释中说明已纠正。开始数值求解前，先在当前目录写入
                        `input_parameter_audit.csv`，逐行记录本题使用的题面参数、单位、来源和代码断言结果；整个问题只能使用一套自洽单位制，禁止把 mm³/ms、mg/mm³、MPa 与 SI 单位混算。
                        每项必须覆盖要求都要在代码输出中逐项说明验证结果；
                        若约束不满足，明确标记为不可行，禁止称为最优解。
                        这是正式题 {key}，不是探索性草稿。结束前必须在当前任务目录写入
                        `{key}_results.csv`：每一行必须是本题将写入论文的一个有限数值，至少包括
                        指标名、数值、单位、计算口径；所有图表另存同名或明确关联的 CSV 数据源。
                        必须从真实数组/CSV计算并输出：目标偏差、压力（或其他物理状态）的最小值、
                        最大值和波动指标、质量/流量平衡残差。不得以截断/clip 掩盖负压力或无效状态；
                        若出现非物理状态，修正控制参数或离散化后重新计算。
                        不得把“估计”“沿用上一问”“同步原则直接取值”伪装成本题的仿真或优化结论：
                        每个正式问题均须实际运行本题模型、保存原始时序/扫描数据，并让结果 CSV 的计算口径
                        明确指向该次计算。涉及阀门控制时，除名义稳态外还须人为施加可复算的扰动/超压工况，
                        保存执行器实际动作次数和响应数据；仅给阈值、或动作次数为零，均不构成控制验证。
                        对题面明确的 100 MPa 压力目标，正式结果的压力峰峰值必须不超过 15 MPa；若首次计算超过该值，
                        必须继续优化控制参数、步长或相位并保存新的时序数据，不能把大幅振荡称为“稳定”。
                        本题完成时必须有可复算的数值结论和可追溯数据文件，不能只保存 PNG、
                        不能只给定性控制方案，也不能只输出中间扫描。
                        `feasible=false` 是一次求解失败而不是正式交付：若首次仿真不满足目标，必须在本子任务内检查单位、质量守恒、控制变量边界和数值步长，修正后重新求解；只有确实证明题面可行域为空时才能报告不可行，并给出可复算的矛盾证据。
                        {plan_context(key)}
                        完成如下问题{value}
                    """,
            }
            for key, value in questions_quesx.items()
        }
        flows = {
            "eda": {
                "coder_prompt": f"""
                        {contract_prompt}
                        参考建模手给出的解决方案{solutions.get("eda", "对数据进行探索性分析")}
                        先根据系统消息中的“当前文件夹下的数据集文件”判断是否真的存在外部数据集。
                        如果数据集文件列表为空，说明题目没有提供样本数据：不得随机生成样本、不得创建“模拟数据集.csv”，
                        不要做直方图、箱线图、缺失值/异常值清洗等数据驱动 EDA；只做题目给定参数表、单位一致性、
                        约束可行性、边界点或可行域核验，并把核验结果打印出来供写作引用。
                        如果确实存在数据集，再对当前目录下数据进行EDA分析(数据清洗,可视化)，清洗后的数据保存当前目录下，**不需要复杂的模型**
                    """,
            },
            **ques_flow,
            "sensitivity_analysis": {
                "coder_prompt": f"""
                        {contract_prompt}
                        参考建模手给出的解决方案{solutions.get("sensitivity_analysis", "对模型进行灵敏度分析")}
                        完成敏感性分析。
                        敏感性分析不是新增题目问题；当前正式题目问题数为 {len(questions_quesx)}。
                        除非题目原文确实存在对应问题，不要把图片或CSV命名为“问题{len(questions_quesx) + 1}_...”。
                        请使用“灵敏度分析_...”或“扩展分析_...”作为敏感性分析输出文件前缀。
                    """,
            },
        }
        return flows

    def get_write_flows(
        self, user_output: UserOutput, config_template: dict, bg_ques_all: str
    ):
        """生成写作阶段的流程配置。

        Args:
            user_output: 用户输出对象，包含已求解的结果。
            config_template: 论文模板配置。
            bg_ques_all: 问题背景和题目信息。

        Returns:
            写作流程配置字典，键为章节名，值为写作提示。
        """
        model_build_solve = user_output.get_model_build_solve()
        flows = {
            "firstPage": f"""问题背景{bg_ques_all},不需要编写代码,根据模型的求解的信息{model_build_solve}，按照如下模板撰写：{config_template["firstPage"]}，撰写标题，摘要，关键词""",
            "RepeatQues": f"""问题背景{bg_ques_all},不需要编写代码,根据模型的求解的信息{model_build_solve}，按照如下模板撰写：{config_template["RepeatQues"]}，撰写问题重述""",
            "analysisQues": f"""问题背景{bg_ques_all},不需要编写代码,根据模型的求解的信息{model_build_solve}，按照如下模板撰写：{config_template["analysisQues"]}，撰写问题分析""",
            "modelAssumption": f"""问题背景{bg_ques_all},不需要编写代码,根据模型的求解的信息{model_build_solve}，按照如下模板撰写：{config_template["modelAssumption"]}，撰写模型假设""",
            "symbol": f"""不需要编写代码,根据模型的求解的信息{model_build_solve}，按照如下模板撰写：{config_template["symbol"]}，撰写符号说明部分""",
            "judge": f"""不需要编写代码,根据模型的求解的信息{model_build_solve}，按照如下模板撰写：{config_template["judge"]}，撰写模型的评价部分""",
        }
        return flows

    def get_writer_prompt(
        self,
        key: str,
        coder_response: str,
        code_interpreter: BaseCodeInterpreter,
        config_template: dict,
    ) -> str:
        """根据不同的key生成对应的writer_prompt

        Args:
            key: 任务类型
            coder_response: 代码执行结果

        Returns:
            str: 生成的writer_prompt
        """
        try:
            code_output = code_interpreter.get_code_output(key)
        except KeyError:
            # Resume restores the notebook kernel (or a variable snapshot), but
            # older checkpoints do not persist the interpreter's per-section
            # output cache.  The durable Coder response and frozen result facts
            # remain available, so a missing cache entry must not block Writer.
            logger.warning(
                "代码输出缓存缺失，使用已持久化的 Coder 响应继续写作: %s", key
            )
            code_output = ""
        result_fact_summary = build_result_fact_summary(code_interpreter.work_dir)
        freeze_validation = validate_result_freeze(code_interpreter.work_dir)
        if freeze_validation["active"]:
            # The code hand-off is useful for method narration, but cannot be a
            # second numerical truth source once a result freeze exists.
            code_context = _redact_computed_numbers(
                f"{coder_response}\n{code_output}"
            )
            result_instruction = (
                "冻结结果已启用：只能使用下方冻结指标中的计算数值。上方执行说明中的"
                "[冻结数值] 不是可引用数值；不得据此补写、估计或改写结果。"
            )
        else:
            code_context = f"{coder_response}\n{code_output}"
            result_instruction = (
                "未提供冻结结果时，只能使用明确列出的结构化结果事实；"
                "不确定的数值不要写入摘要、图题或结论。"
            )

        questions_quesx_keys = self.get_questions_quesx_keys()
        bgc = self.questions["background"]
        quesx_writer_prompt = {
            key: f"""
                    问题背景{bgc},不需要编写代码。执行说明（仅供方法叙述）{code_context}
                    {result_fact_summary}
                    {result_instruction}
                    按照如下模板撰写：{config_template[key]}
                """
            for key in questions_quesx_keys
        }

        writer_prompt = {
            "eda": f"""
                    问题背景{bgc},不需要编写代码。执行说明（仅供方法叙述）{code_context}
                    {result_fact_summary}
                    {result_instruction}
                    按照如下模板撰写：{config_template["eda"]}
                """,
            **quesx_writer_prompt,
            "sensitivity_analysis": f"""
                    问题背景{bgc},不需要编写代码。执行说明（仅供方法叙述）{code_context}
                    {result_fact_summary}
                    {result_instruction}
                    按照如下模板撰写：{config_template["sensitivity_analysis"]}
                    注意：敏感性分析不是新增题目问题。若题目重述只列出两问，不要在正文、图题或表题中称其为“问题三/问题3”；如图片路径历史上含“问题3_”，括号中的路径保持不变，方括号中的图题和正文表述改写为“灵敏度分析_...”或“扩展分析_...”。
                """,
        }

        if key in writer_prompt:
            return writer_prompt[key]
        else:
            raise ValueError(f"未知的任务类型: {key}")

    def get_questions_quesx_keys(self) -> list[str]:
        """获取问题1,2...的键"""
        return list(self.get_questions_quesx().keys())

    def get_questions_quesx(self) -> dict[str, str | int]:
        """获取问题1,2,3...的键值对"""
        # 获取所有以 "ques" 开头的键值对
        questions_quesx = {
            key: value
            for key, value in self.questions.items()
            if key.startswith("ques") and key != "ques_count"
        }
        return questions_quesx

    def get_seq(self, ques_count: int) -> dict[str, str]:
        """获取论文章节顺序。

        Args:
            ques_count: 问题数量。

        Returns:
            以章节名为键的有序字典。
        """
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
        return {key: "" for key in seq}
