"""文件管理路由模块，提供文件下载、列表和目录打开等接口。"""

from fastapi import APIRouter
from fastapi.responses import FileResponse
from app.config.setting import settings
from app.utils.common_utils import (
    ensure_safe_filename,
    ensure_safe_task_id,
    get_current_files,
    get_work_dir,
    safe_join_work_dir,
)
import os
import tempfile
import zipfile
from fastapi import HTTPException

router = APIRouter()

ARCHIVE_FILENAME = "all.zip"
MAX_ARCHIVE_FILE_SIZE_BYTES = 50 * 1024 * 1024
MAX_ARCHIVE_TOTAL_SIZE_BYTES = 200 * 1024 * 1024
EXCLUDED_ARCHIVE_DIRS = {
    ".git",
    ".ipynb_checkpoints",
    "__pycache__",
}
EXCLUDED_ARCHIVE_SUFFIXES = (
    ".tmp",
    ".temp",
    ".part",
    ".lock",
)
INTERNAL_ARCHIVE_FILENAMES = {
    # A manually preserved recovery PDF is useful for diagnosis, but is not a
    # primary deliverable and must not be mixed into the user's download-all
    # submission bundle.
    "res_recovery_candidate.pdf",
}
INLINE_RASTER_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}


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


def _should_skip_archive_file(filename: str) -> bool:
    lowered = filename.lower()
    return (
        lowered == ARCHIVE_FILENAME
        or lowered in INTERNAL_ARCHIVE_FILENAMES
        or lowered.endswith(EXCLUDED_ARCHIVE_SUFFIXES)
    )


def _collect_archive_files(work_dir: str) -> list[tuple[str, str, int]]:
    """收集可安全打包的文件，返回 (绝对路径, zip 内相对路径, 文件大小)。"""
    root = os.path.abspath(work_dir)
    real_root = os.path.realpath(root)
    collected: list[tuple[str, str, int]] = []
    total_size = 0

    for current_dir, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            dirname
            for dirname in dirnames
            if dirname not in EXCLUDED_ARCHIVE_DIRS and not dirname.startswith(".")
        )
        dirnames[:] = [
            dirname
            for dirname in dirnames
            if not os.path.islink(os.path.join(current_dir, dirname))
        ]
        for filename in sorted(filenames):
            if _should_skip_archive_file(filename):
                continue
            file_path = os.path.abspath(os.path.join(current_dir, filename))
            if os.path.commonpath([root, file_path]) != root:
                continue
            if os.path.islink(file_path):
                continue
            real_file_path = os.path.realpath(file_path)
            if os.path.commonpath([real_root, real_file_path]) != real_root:
                continue
            if not os.path.isfile(file_path):
                continue

            file_size = os.path.getsize(file_path)
            if file_size > MAX_ARCHIVE_FILE_SIZE_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=f"文件过大，无法打包: {filename}",
                )
            total_size += file_size
            if total_size > MAX_ARCHIVE_TOTAL_SIZE_BYTES:
                raise HTTPException(status_code=413, detail="任务文件总大小超过打包上限")

            archive_name = os.path.relpath(file_path, root).replace(os.sep, "/")
            collected.append((file_path, archive_name, file_size))

    return collected


def _create_task_archive(work_dir: str) -> str:
    archive_path = os.path.join(work_dir, ARCHIVE_FILENAME)
    files = _collect_archive_files(work_dir)
    temp_fd, temp_archive_path = tempfile.mkstemp(
        prefix=f"{ARCHIVE_FILENAME}.",
        suffix=".tmp",
        dir=work_dir,
    )
    os.close(temp_fd)

    try:
        with zipfile.ZipFile(
            temp_archive_path,
            "w",
            compression=zipfile.ZIP_DEFLATED,
        ) as archive:
            for file_path, archive_name, _file_size in files:
                archive.write(file_path, archive_name)
        os.replace(temp_archive_path, archive_path)
    except Exception:
        if os.path.exists(temp_archive_path):
            os.remove(temp_archive_path)
        raise
    return archive_path


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


@router.get("/static/{task_id}/{filename}")
async def serve_task_file(task_id: str, filename: str):
    """Serve a single task artifact without exposing the whole work directory.

    Only raster images are rendered inline for the Markdown preview. Every other
    artifact is downloaded with an octet-stream media type so an uploaded or model-
    generated HTML/SVG file cannot execute in the backend origin.
    """
    safe_task_id = _require_safe_task_id(task_id)
    safe_filename = _require_safe_filename(filename)
    file_path = safe_join_work_dir(safe_task_id, safe_filename)
    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="文件不存在")

    suffix = os.path.splitext(safe_filename)[1].lower()
    if suffix in INLINE_RASTER_IMAGE_SUFFIXES:
        media_type = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".webp": "image/webp",
            ".bmp": "image/bmp",
        }[suffix]
        return FileResponse(
            file_path,
            media_type=media_type,
            headers={"Content-Security-Policy": "default-src 'none'; sandbox"},
        )

    return FileResponse(
        file_path,
        media_type="application/octet-stream",
        filename=safe_filename,
        headers={"Content-Security-Policy": "default-src 'none'; sandbox"},
    )


@router.get("/download_all_url")
async def get_download_all_url(task_id: str):
    safe_task_id = _require_safe_task_id(task_id)
    try:
        work_dir = get_work_dir(safe_task_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc
    _create_task_archive(work_dir)
    return {
        "download_url": f"{settings.SERVER_HOST}/static/{safe_task_id}/{ARCHIVE_FILENAME}"
    }


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
