import os
import datetime
import hashlib
import tomllib
from app.utils.enums import CompTemplate
from app.utils.log_util import logger
import re


def create_task_id() -> str:
    """生成任务ID"""
    # 生成时间戳和随机hash
    timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    random_hash = hashlib.md5(str(datetime.datetime.now()).encode()).hexdigest()[:8]
    return f"{timestamp}-{random_hash}"


def create_work_dir(task_id: str) -> str:
    # 设置主工作目录和子目录
    work_dir = os.path.join("project", "work_dir", task_id)

    try:
        # 创建目录，如果目录已存在也不会报错
        os.makedirs(work_dir, exist_ok=True)
        return work_dir
    except Exception as e:
        # 捕获并记录创建目录时的异常
        logger.error(f"创建工作目录失败: {str(e)}")
        raise


def get_work_dir(task_id: str) -> str:
    work_dir = os.path.join("project", "work_dir", task_id)
    if os.path.exists(work_dir):
        return work_dir
    else:
        logger.error(f"工作目录不存在: {work_dir}")
        raise FileNotFoundError(f"工作目录不存在: {work_dir}")


#  TODO: 是不是应该将 Prompt 写成一个 class
def get_config_template(comp_template: CompTemplate = CompTemplate.CHINA) -> dict:
    if comp_template == CompTemplate.CHINA:
        return load_toml(os.path.join("app", "config", "md_template.toml"))


def load_toml(path: str) -> dict:
    with open(path, "rb") as f:
        return tomllib.load(f)


def load_markdown(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def get_current_files(folder_path: str, type: str = "all") -> list[str]:
    files = os.listdir(folder_path)
    if type == "all":
        return files

    elif type == "md":
        return [file for file in files if file.endswith(".md")]
    elif type == "ipynb":
        return [file for file in files if file.endswith(".ipynb")]
    elif type == "data":
        return [
            file for file in files if file.endswith(".xlsx") or file.endswith(".csv")
        ]
    elif type == "image":
        return [
            file for file in files if file.endswith(".png") or file.endswith(".jpg")
        ]


def simple_chat(model, history: list) -> str:
    """
    Description of the function.

    Args:
        model (BaseModel): 模型
        history (list): 构造好的历史记录（包含system_prompt,user_prompt）

    Returns:
        return_type: Description of the return value.
    """
    kwargs = {
        "model": model.model,
        "messages": history,
        "stream": False,
    }

    completion = model.client.chat.completions.create(**kwargs)

    return completion.choices[0].message.content


# 判断content是否包含图片 xx.png,对其处理为    ![filename](http://localhost:8000/static/20250428-200915-ebc154d4/filename.jpg)
def transform_link(task_id: str, content: str):
    content = re.sub(
        r"!\[(.*?)\]\((.*?\.(?:png|jpg|jpeg|gif|bmp|webp))\)",
        lambda match: f"![{match.group(1)}](http://localhost:8000/static/{task_id}/{match.group(2)})",
        content,
    )
    return content
