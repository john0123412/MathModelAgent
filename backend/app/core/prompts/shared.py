"""共享的提示词工具函数。"""


def get_reflection_prompt(error_message, code) -> str:
    """生成代码错误反思提示词。

    Args:
        error_message: 错误信息。
        code: 出错的代码。

    Returns:
        反思提示词字符串。
    """
    timeout_instruction = ""
    if "本地代码执行超过" in str(error_message):
        timeout_instruction = """
This was a hard execution timeout. The local kernel was discarded; it may have
restored durable variables only, not user-defined functions. Do not retry the
same high-cost computation. Replace nested ODE/optimizer/grid loops with a
traceable bounded design: at most 5--9 screening points, a short finite horizon,
and at most one detailed validation point. Save the actual summary CSV before
making figures. If the requested evidence cannot be computed within this budget,
write a feasible=false validation entry rather than inventing a result.
"""
    return f"""The code execution encountered an error:
{error_message}

{timeout_instruction}

Please analyze the error, identify the cause, and provide a corrected version of the code. 
Consider:
1. Syntax errors
2. Missing imports
3. Incorrect variable names or types
4. File path issues
5. Any other potential issues
6. If a task repeatedly fails to complete, try breaking down the code, changing your approach, or simplifying the model. If you still can't do it, I'll "chop" you 🪓 and cut your power 😡.
7. Don't ask user any thing about how to do and next to do,just do it by yourself.

Previous code:
{code}

Please provide an explanation of what went wrong and Remenber call the function tools to retry 
"""


def get_completion_check_prompt(prompt, text_to_gpt) -> str:
    """生成任务完成检查提示词。

    Args:
        prompt: 原始任务描述。
        text_to_gpt: 最新执行结果。

    Returns:
        完成检查提示词字符串。
    """
    return f"""
Please analyze the current state and determine if the task is fully completed:

Original task: {prompt}

Latest execution results:
{text_to_gpt}  # 修改：使用合并后的结果

Consider:
1. Have all required data processing steps been completed?
2. Have all necessary files been saved?
3. Are there any remaining steps needed?
4. Is the output satisfactory and complete?
5. 如果一个任务反复无法完成，尝试切换路径、简化路径或直接跳过，千万别陷入反复重试，导致死循环。
6. 尽量在较少的对话轮次内完成任务
7. If the task is complete, please provide a short summary of what was accomplished and don't call function tool.
8. If the task is not complete, please rethink how to do and call function tool
9. Don't ask user any thing about how to do and next to do,just do it by yourself
10. have a good visualization?
"""
