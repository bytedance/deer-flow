"""
工件（Artifacts）API 路由模块 - 处理AI生成的文件输出

===================
设计思路说明
===================

**为什么需要这个模块**：
1. **文件访问服务**：提供安全访问AI生成文件的HTTP接口
2. **格式自适应**：根据文件类型自动选择合适的响应方式
3. **安全防护**：防止恶意内容通过生成的文件执行

**核心设计模式**：
- 策略模式：根据MIME类型选择不同的响应策略
- 防御性编程：对所有文件访问进行安全验证
- 适配器模式：将ZIP存档内的文件适配为可访问的HTTP资源

**为什么这样设计**：
- **分层安全**：路径验证 + 类型检查 + 内容验证
- **灵活下载**：支持内联查看和强制下载两种模式
- **存档支持**：可以直接访问 .skill ZIP 包内的文件

**关键概念**：
- **工件（Artifact）**：AI代理生成的文件输出
- **虚拟路径**：沙箱内看到的路径（如 /mnt/user-data/outputs/...）
- **活跃内容**：可能包含脚本的可执行内容（HTML/XHTML/SVG）
- **.skill 存档**：包含技能定义的 ZIP 文件

**安全策略**：
1. **活跃内容强制下载**：HTML/XHTML/SVG 文件必须下载，不能内联显示
2. **路径验证**：防止路径遍历攻击
3. **内容检测**：检查文件是否为文本类型
"""

import logging
import mimetypes
import zipfile
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse, Response

from app.gateway.path_utils import resolve_thread_virtual_path

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["artifacts"])

# 活跃内容 MIME 类型集合
# 为什么需要这个集合：
# 1. 这些类型可能包含可执行脚本（JavaScript 在 HTML 中）
# 2. 内联显示可能导致 XSS 攻击
# 3. 强制下载可以避免在应用源上下文中执行
ACTIVE_CONTENT_MIME_TYPES = {
    "text/html",           # HTML 文件可能包含 JavaScript
    "application/xhtml+xml", # XHTML 同样可能包含脚本
    "image/svg+xml",       # SVG 可以包含 JavaScript 脚本
}


def _build_content_disposition(disposition_type: str, filename: str) -> str:
    """
    构建 RFC 5987 编码的 Content-Disposition 头部值

    ===================
    设计思路说明
    ===================

    **核心职责**：
    创建符合 RFC 5987 标准的 Content-Disposition 头部，支持非 ASCII 文件名。

    **为什么这样设计**：
    - **RFC 5987 编码**：使用 UTF-8 编码支持国际文件名
    - **URL 编码**：对文件名进行百分号编码，处理特殊字符
    - **标准兼容**：遵循 RFC 5987，确保浏览器兼容性

    **参数说明**：
    - disposition_type: disposition 类型（"inline" 或 "attachment"）
    - filename: 原始文件名（可能包含非 ASCII 字符）

    **返回值**：
    - 格式化的 Content-Disposition 头部值
    - 示例：attachment; filename*=UTF-8''%E4%B8%AD%E6%96%87.txt

    **为什么使用 RFC 5987**：
    - 传统方式只支持 ASCII 文件名
    - RFC 5987 扩展支持 UTF-8 编码
    - 现代浏览器广泛支持
    """

    return f"{disposition_type}; filename*=UTF-8''{quote(filename)}"


def _build_attachment_headers(filename: str, extra_headers: dict[str, str] | None = None) -> dict[str, str]:
    """
    构建文件下载的响应头部

    **核心职责**：
    创建包含 Content-Disposition 的下载响应头部集合。

    **为什么这样设计**：
    - **可扩展性**：允许添加额外的自定义头部
    - **默认下载**：默认使用 attachment disposition
    - **标准化**：使用统一的头部构建函数

    **参数说明**：
    - filename: 下载时显示的文件名
    - extra_headers: 可选的额外头部（如缓存控制）

    **返回值**：
    - 包含 Content-Disposition 和额外头部的字典
    """

    headers = {"Content-Disposition": _build_content_disposition("attachment", filename)}
    if extra_headers:
        headers.update(extra_headers)
    return headers


def is_text_file_by_content(path: Path, sample_size: int = 8192) -> bool:
    """
    通过检查内容判断文件是否为文本文件

    ===================
    设计思路说明
    ===================

    **核心职责**：
    基于文件内容（而非扩展名）判断是否为文本文件。

    **为什么这样设计**：
    - **内容检测**：不依赖文件扩展名，更可靠
    - **空字节检测**：文本文件不应包含空字节
    - **采样检测**：只读取前 8KB，提高性能

    **为什么选择 8192 作为采样大小**：
    - 足够检测大多数二进制文件的标记
    - 不会读取过多数据影响性能
    - 是常见的页大小，对文件系统友好

    **参数说明**：
    - path: 文件路径
    - sample_size: 采样字节数（默认 8192）

    **返回值**：
    - True: 文件看起来像文本
    - False: 文件包含二进制内容
    """

    try:
        with open(path, "rb") as f:
            chunk = f.read(sample_size)
            # 文本文件不应该包含空字节
            # 空字节在二进制文件中很常见，但在文本中罕见
            return b"\x00" not in chunk
    except Exception:
        # 读取失败时保守地返回 False
        return False


def _extract_file_from_skill_archive(zip_path: Path, internal_path: str) -> bytes | None:
    """
    从 .skill ZIP 存档中提取文件

    ===================
    设计思路说明
    ===================

    **核心职责**：
    从技能包（.skill ZIP 文件）中提取指定文件的内容。

    **为什么需要这个功能**：
    1. **技能包结构**：.skill 文件是包含多个文件的 ZIP 存档
    2. **透明访问**：允许直接访问存档内的文件而无需解压
    3. **技能预览**：支持查看 SKILL.md 等定义文件

    **为什么这样设计**：
    - **多级查找**：先尝试直接路径，再尝试带目录前缀的路径
    - **错误容忍**：无效的 ZIP 文件返回 None 而非抛出异常
    - **性能优化**：使用 is_zipfile 先验证，避免无效处理

    **查找策略**：
    1. 直接路径：如 "SKILL.md"
    2. 单级目录前缀：如 "skill-name/SKILL.md"
    3. 返回第一个匹配的文件

    **参数说明**：
    - zip_path: .skill 文件（ZIP 存档）的路径
    - internal_path: 存档内的文件路径（如 "SKILL.md"）

    **返回值**：
    - 文件内容的字节串，如果未找到则返回 None

    **为什么返回 None 而非抛出异常**：
    - 文件不存在是正常情况（调用方会处理）
    - 简化调用方的错误处理逻辑
    - 与 "文件不存在" 的语义一致
    """

    if not zipfile.is_zipfile(zip_path):
        return None

    try:
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            # 获取存档中的所有文件列表
            namelist = zip_ref.namelist()

            # 首先尝试直接路径匹配
            if internal_path in namelist:
                return zip_ref.read(internal_path)

            # 尝试匹配带顶级目录前缀的路径
            # 例如：internal_path="SKILL.md" 可能匹配 "my-skill/SKILL.md"
            for name in namelist:
                if name.endswith("/" + internal_path) or name == internal_path:
                    return zip_ref.read(name)

            # 未找到匹配的文件
            return None
    except (zipfile.BadZipFile, KeyError):
        return None


@router.get(
    "/threads/{thread_id}/artifacts/{path:path}",
    summary="Get Artifact File",
    description="Retrieve an artifact file generated by the AI agent. Text and binary files can be viewed inline, while active web content is always downloaded.",
)
async def get_artifact(thread_id: str, path: str, request: Request, download: bool = False) -> Response:
    """
    获取 AI 代理生成的工件文件

    ===================
    设计思路说明
    ===================

    **核心职责**：
    根据虚拟路径获取工件文件，并根据文件类型选择合适的响应方式。

    **为什么这样设计**：
    - **自动类型检测**：根据 MIME 类型自动选择响应方式
    - **安全优先**：活跃内容强制下载，防止 XSS 攻击
    - **存档支持**：可以直接访问 .skill 包内的文件
    - **灵活下载**：通过 download 参数控制下载行为

    **响应策略**：
    1. **活跃内容**（HTML/XHTML/SVG）：总是作为下载附件
    2. **文本文件**：作为纯文本返回，支持内联查看
    3. **二进制文件**：内联显示，提供下载选项
    4. **存档文件**：从 ZIP 中提取后按上述策略处理

    **为什么活跃内容总是下载**：
    - 防止脚本在应用源上下文中执行
    - 避免潜在的 XSS 攻击
    - 即使用户请求内联也强制下载

    **为什么支持 .skill 存档访问**：
    - .skill 文件是技能包的 ZIP 格式
    - 用户可能想查看技能定义而不下载整个包
    - 支持预览 SKILL.md 等文档

    **参数说明**：
    - thread_id: 线程 ID
    - path: 工件的虚拟路径（如 mnt/user-data/outputs/file.txt）
    - request: FastAPI 请求对象（自动注入）
    - download: 是否强制下载（查询参数）

    **返回值**：
    - FileResponse: 用于常规文件下载
    - PlainTextResponse: 用于文本文件内联显示
    - Response: 用于从存档提取的内容或二进制数据

    **异常**：
    - HTTPException(400): 路径无效或不是文件
    - HTTPException(403): 访问被拒绝（检测到路径遍历）
    - HTTPException(404): 文件未找到

    **缓存策略**：
    - 存档文件添加 5 分钟缓存，避免重复解压
    - 使用 Cache-Control: private, max-age=300
    """

    # 检查是否为 .skill 存档内的文件请求
    # 例如：xxx.skill/SKILL.md
    if ".skill/" in path:
        # 在 ".skill/" 处分割路径
        skill_marker = ".skill/"
        marker_pos = path.find(skill_marker)
        skill_file_path = path[: marker_pos + len(".skill")]  # 例如："mnt/user-data/outputs/my-skill.skill"
        internal_path = path[marker_pos + len(skill_marker) :]  # 例如："SKILL.md"

        # 解析 .skill 文件的实际路径
        actual_skill_path = resolve_thread_virtual_path(thread_id, skill_file_path)

        if not actual_skill_path.exists():
            raise HTTPException(status_code=404, detail=f"Skill file not found: {skill_file_path}")

        if not actual_skill_path.is_file():
            raise HTTPException(status_code=400, detail=f"Path is not a file: {skill_file_path}")

        # 从 .skill 存档中提取文件
        content = _extract_file_from_skill_archive(actual_skill_path, internal_path)
        if content is None:
            raise HTTPException(status_code=404, detail=f"File '{internal_path}' not found in skill archive")

        # 根据内部文件确定 MIME 类型
        mime_type, _ = mimetypes.guess_type(internal_path)
        # 添加缓存头部以避免重复 ZIP 提取（缓存 5 分钟）
        cache_headers = {"Cache-Control": "private, max-age=300"}
        download_name = Path(internal_path).name or actual_skill_path.stem

        # 如果请求下载或是活跃内容，返回附件
        if download or mime_type in ACTIVE_CONTENT_MIME_TYPES:
            return Response(
                content=content,
                media_type=mime_type or "application/octet-stream",
                headers=_build_attachment_headers(download_name, cache_headers)
            )

        # 文本类型作为纯文本返回
        if mime_type and mime_type.startswith("text/"):
            return PlainTextResponse(
                content=content.decode("utf-8"),
                media_type=mime_type,
                headers=cache_headers
            )

        # 默认对未知类型尝试纯文本，失败则返回原始内容
        try:
            return PlainTextResponse(
                content=content.decode("utf-8"),
                media_type="text/plain",
                headers=cache_headers
            )
        except UnicodeDecodeError:
            return Response(
                content=content,
                media_type=mime_type or "application/octet-stream",
                headers=cache_headers
            )

    # 常规文件处理：解析虚拟路径到实际路径
    actual_path = resolve_thread_virtual_path(thread_id, path)

    logger.info(f"Resolving artifact path: thread_id={thread_id}, requested_path={path}, actual_path={actual_path}")

    if not actual_path.exists():
        raise HTTPException(status_code=404, detail=f"Artifact not found: {path}")

    if not actual_path.is_file():
        raise HTTPException(status_code=400, detail=f"Path is not a file: {path}")

    # 根据文件扩展名猜测 MIME 类型
    mime_type, _ = mimetypes.guess_type(actual_path)

    # 如果请求下载，返回文件响应
    if download:
        return FileResponse(
            path=actual_path,
            filename=actual_path.name,
            media_type=mime_type,
            headers=_build_attachment_headers(actual_path.name)
        )

    # 活跃内容类型总是强制下载
    # 防止脚本在应用源上下文中执行
    # 这是一种安全措施，避免用户打开生成的工件时执行恶意脚本
    if mime_type in ACTIVE_CONTENT_MIME_TYPES:
        return FileResponse(
            path=actual_path,
            filename=actual_path.name,
            media_type=mime_type,
            headers=_build_attachment_headers(actual_path.name)
        )

    # 文本类型作为纯文本返回
    if mime_type and mime_type.startswith("text/"):
        return PlainTextResponse(
            content=actual_path.read_text(encoding="utf-8"),
            media_type=mime_type
        )

    # 对于未知类型，通过内容检测判断
    if is_text_file_by_content(actual_path):
        return PlainTextResponse(
            content=actual_path.read_text(encoding="utf-8"),
            media_type=mime_type
        )

    # 二进制文件内联返回，支持下载
    return Response(
        content=actual_path.read_bytes(),
        media_type=mime_type,
        headers={"Content-Disposition": _build_content_disposition("inline", actual_path.name)}
    )
