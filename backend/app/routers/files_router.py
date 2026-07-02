"""文件管理路由模块，提供文件下载、列表和目录打开等接口。"""

from fastapi import APIRouter
from app.config.setting import settings
from app.utils.common_utils import (
    ensure_safe_filename,
    ensure_safe_task_id,
    get_current_files,
    get_work_dir,
    safe_join_work_dir,
)
import os
import subprocess
from icecream import ic  # type: ignore[import-unresolved]
from fastapi import HTTPException

router = APIRouter()


def _require_safe_task_id(task_id: str) -> str:
    try:
        return ensure_safe_task_id(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="非法任务ID") from exc


def _require_safe_filename(filename: str) -> str:
    try:
        return ensure_safe_filename(filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="非法文件名") from exc


@router.get("/download_url")
async def get_download_url(task_id: str, filename: str):
    safe_task_id = _require_safe_task_id(task_id)
    safe_filename = _require_safe_filename(filename)
    file_path = safe_join_work_dir(safe_task_id, safe_filename)
    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="文件不存在")
    return {
        "download_url": f"{settings.SERVER_HOST}/static/{safe_task_id}/{safe_filename}"
    }


@router.get("/download_all_url")
async def get_download_all_url(task_id: str):
    safe_task_id = _require_safe_task_id(task_id)
    return {"download_url": f"{settings.SERVER_HOST}/static/{safe_task_id}/all.zip"}


@router.get("/files")
async def get_files(task_id: str):
    safe_task_id = _require_safe_task_id(task_id)
    work_dir = get_work_dir(safe_task_id)
    files = get_current_files(work_dir, "all")
    file_all = []

    for i in files:
        file_type = i.split(".")[-1]
        file_all.append({"filename": i, "file_type": file_type})

    return file_all


@router.get("/open_folder")
async def open_folder(task_id: str):
    if settings.ENV.lower() != "dev":
        raise HTTPException(status_code=403, detail="仅开发环境允许打开本地目录")
    safe_task_id = _require_safe_task_id(task_id)
    ic(safe_task_id)
    # 打开工作目录
    work_dir = get_work_dir(safe_task_id)

    # 打开工作目录
    if os.name == "nt":
        subprocess.run(["explorer", work_dir])
    elif os.name == "posix":
        subprocess.run(["open", work_dir])
    else:
        raise HTTPException(status_code=500, detail=f"不支持的操作系统: {os.name}")

    return {"message": "打开工作目录成功", "work_dir": work_dir}
