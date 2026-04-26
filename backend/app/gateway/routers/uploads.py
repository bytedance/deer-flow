"""
上传（Uploads）路由端点 — 处理文件上传

===================
设计思路说明
===================

**核心职责**：
1. 接收用户上传的文件
2. 自动转换Office文档和PDF为Markdown
3. 同步文件到沙箱环境
4. 提供文件列表和删除功能

**为什么需要这个路由**：
- AI Agent处理任务时需要参考用户提供的文档
- 用户上传的文件需要被Agent安全地访问
- Office文档需要转换为Markdown才能被LLM理解

**核心设计原则**：
- 线程隔离：每个线程的文件相互独立
- 安全验证：防止目录遍历攻击
- 自动转换：提升文档可读性
- 沙箱同步：确保Agent能访问文件

**为什么使用"线程目录优先"策略**：
- 权威存储在线程目录
- 本地沙箱直接使用
- 远程沙箱自动同步
"""

from __future__ import annotations

import logging
import os
import stat

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from deerflow.config.paths import get_paths
from deerflow.sandbox.sandbox_provider import get_sandbox_provider
from deerflow.uploads.manager import (
    PathTraversalError,
    delete_file_safe,
    enrich_file_listing,
    ensure_uploads_dir,
    get_uploads_dir,
    list_files_in_dir,
    normalize_filename,
    upload_artifact_url,
    upload_virtual_path,
)
from deerflow.utils.file_conversion import CONVERTIBLE_EXTENSIONS, convert_file_to_markdown

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/threads/{thread_id}/uploads", tags=["uploads"])


class UploadResponse(BaseModel):
    """文件上传响应模型"""

    success: bool
    files: list[dict[str, str]]
    message: str


def _make_file_sandbox_writable(file_path: os.PathLike[str] | str) -> None:
    """
    确保上传的文件在挂载到非本地沙箱时保持可写

    **为什么需要这个函数**：
    - AIO沙箱模式下，gateway先写入权威host端文件
    - 然后沙箱运行时可能重写相同的挂载路径
    - 授予全局可写权限防止权限不匹配

    **为什么跳过符号链接**：
    - 符号链接可能指向其他位置
    - 修改权限可能影响其他文件
    - 安全考虑

    **参数说明**：
        file_path: 文件路径
    """
    file_stat = os.lstat(file_path)
    if stat.S_ISLNK(file_stat.st_mode):
        logger.warning("Skipping sandbox chmod for symlinked upload path: %s", file_path)
        return

    writable_mode = stat.S_IMODE(file_stat.st_mode) | stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH
    chmod_kwargs = {"follow_symlinks": False} if os.chmod in os.supports_follow_symlinks else {}
    os.chmod(file_path, writable_mode, **chmod_kwargs)


@router.post("", response_model=UploadResponse)
async def upload_files(
    thread_id: str,
    files: list[UploadFile] = File(...),
) -> UploadResponse:
    """
    上传多个文件到线程的上传目录

    **上传流程**：
    1. 验证文件名安全性
    2. 写入到线程的上传目录
    3. 如果是可转换文档，转换为Markdown
    4. 同步到沙箱环境（如果非本地）

    **为什么需要同步到沙箱**：
    - Agent在沙箱中运行
    - 需要访问用户上传的文件
    - 非本地沙箱需要显式同步

    **参数说明**：
        thread_id: 线程ID
        files: 要上传的文件列表

    **异常**：
        HTTPException 400: 没有提供文件或thread_id无效
        HTTPException 500: 上传失败

    **返回值**：
        包含成功文件列表和消息的上传响应
    """
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")

    try:
        uploads_dir = ensure_uploads_dir(thread_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    sandbox_uploads = get_paths().sandbox_uploads_dir(thread_id)
    uploaded_files = []

    sandbox_provider = get_sandbox_provider()
    sandbox_id = sandbox_provider.acquire(thread_id)
    sandbox = sandbox_provider.get(sandbox_id)

    for file in files:
        if not file.filename:
            continue

        try:
            safe_filename = normalize_filename(file.filename)
        except ValueError:
            logger.warning(f"Skipping file with unsafe filename: {file.filename!r}")
            continue

        try:
            content = await file.read()
            file_path = uploads_dir / safe_filename
            file_path.write_bytes(content)

            virtual_path = upload_virtual_path(safe_filename)

            if sandbox_id != "local":
                _make_file_sandbox_writable(file_path)
                sandbox.update_file(virtual_path, content)

            file_info = {
                "filename": safe_filename,
                "size": str(len(content)),
                "path": str(sandbox_uploads / safe_filename),
                "virtual_path": virtual_path,
                "artifact_url": upload_artifact_url(thread_id, safe_filename),
            }

            logger.info(f"Saved file: {safe_filename} ({len(content)} bytes) to {file_info['path']}")

            file_ext = file_path.suffix.lower()
            if file_ext in CONVERTIBLE_EXTENSIONS:
                md_path = await convert_file_to_markdown(file_path)
                if md_path:
                    md_virtual_path = upload_virtual_path(md_path.name)

                    if sandbox_id != "local":
                        _make_file_sandbox_writable(md_path)
                        sandbox.update_file(md_virtual_path, md_path.read_bytes())

                    file_info["markdown_file"] = md_path.name
                    file_info["markdown_path"] = str(sandbox_uploads / md_path.name)
                    file_info["markdown_virtual_path"] = md_virtual_path
                    file_info["markdown_artifact_url"] = upload_artifact_url(thread_id, md_path.name)

            uploaded_files.append(file_info)

        except Exception as e:
            logger.error(f"Failed to upload {file.filename}: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to upload {file.filename}: {str(e)}")

    return UploadResponse(
        success=True,
        files=uploaded_files,
        message=f"Successfully uploaded {len(uploaded_files)} file(s)",
    )


@router.get("/list", response_model=dict)
async def list_uploaded_files(thread_id: str) -> dict:
    """
    列出线程上传目录中的所有文件

    **为什么需要这个端点**：
    - 用户查看已上传的文件
    - 前端显示文件列表
    - 调试和验证

    **参数说明**：
        thread_id: 线程ID

    **异常**：
        HTTPException 400: thread_id无效

    **返回值**：
        包含文件列表和计数的字典
    """
    try:
        uploads_dir = get_uploads_dir(thread_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    result = list_files_in_dir(uploads_dir)
    enrich_file_listing(result, thread_id)

    # Gateway额外包含沙箱相对路径
    sandbox_uploads = get_paths().sandbox_uploads_dir(thread_id)
    for f in result["files"]:
        f["path"] = str(sandbox_uploads / f["filename"])

    return result


@router.delete("/{filename}")
async def delete_uploaded_file(thread_id: str, filename: str) -> dict:
    """
    从线程的上传目录中删除文件

    **删除逻辑**：
    - 删除原始文件
    - 如果存在转换后的Markdown，也删除
    - 验证路径安全性

    **参数说明**：
        thread_id: 线程ID
        filename: 要删除的文件名

    **异常**：
        HTTPException 400: 无效路径
        HTTPException 404: 文件不存在
        HTTPException 500: 删除失败

    **返回值**：
        包含成功消息的字典
    """
    try:
        uploads_dir = get_uploads_dir(thread_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    try:
        return delete_file_safe(uploads_dir, filename, convertible_extensions=CONVERTIBLE_EXTENSIONS)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"File not found: {filename}")
    except PathTraversalError:
        raise HTTPException(status_code=400, detail="Invalid path")
    except Exception as e:
        logger.error(f"Failed to delete {filename}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete {filename}: {str(e)}")
