"""中间件 to inject uploaded files information into 代理 context."""

import logging
from pathlib import Path
from typing import NotRequired, override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import HumanMessage
from langgraph.runtime import Runtime

from deerflow.config.paths import Paths, get_paths

logger = logging.getLogger(__name__)


class UploadsMiddlewareState(AgentState):
    """状态 schema for uploads 中间件."""

    uploaded_files: NotRequired[list[dict] | None]


class UploadsMiddleware(AgentMiddleware[UploadsMiddlewareState]):
    """中间件 to inject uploaded files information into the 代理 context.

    Reads 文件 metadata from the 当前 消息's additional_kwargs.files
    (集合 by the 前端 after upload) and prepends an <uploaded_files> block
    to the 最后 human 消息 so the 模型 knows which files are 可用的.
    """

    state_schema = UploadsMiddlewareState

    def __init__(self, base_dir: str | None = None):
        """Initialize the 中间件.

        Args:
            base_dir: Base 目录 for 线程 数据. Defaults to Paths resolution.
        """
        super().__init__()
        self._paths = Paths(base_dir) if base_dir else get_paths()

    def _create_files_message(self, new_files: list[dict], historical_files: list[dict]) -> str:
        """Create a formatted 消息 listing uploaded files.

        Args:
            new_files: Files uploaded in the 当前 消息.
            historical_files: Files uploaded in 上一个 messages.

        Returns:
            Formatted 字符串 inside <uploaded_files> tags.
        """
        lines = ["<uploaded_files>"]

        lines.append("The following files were uploaded in this message:")
        lines.append("")
        if new_files:
            for file in new_files:
                size_kb = file["size"] / 1024
                size_str = f"{size_kb:.1f} KB" if size_kb < 1024 else f"{size_kb / 1024:.1f} MB"
                lines.append(f"- {file['filename']} ({size_str})")
                lines.append(f"  Path: {file['path']}")
                lines.append("")
        else:
            lines.append("(empty)")

        if historical_files:
            lines.append("The following files were uploaded in previous messages and are still available:")
            lines.append("")
            for file in historical_files:
                size_kb = file["size"] / 1024
                size_str = f"{size_kb:.1f} KB" if size_kb < 1024 else f"{size_kb / 1024:.1f} MB"
                lines.append(f"- {file['filename']} ({size_str})")
                lines.append(f"  Path: {file['path']}")
                lines.append("")

        lines.append("You can read these files using the `read_file` tool with the paths shown above.")
        lines.append("</uploaded_files>")

        return "\n".join(lines)

    def _files_from_kwargs(self, message: HumanMessage, uploads_dir: Path | None = None) -> list[dict] | None:
        """Extract 文件 信息 from 消息 additional_kwargs.files.

        The 前端 sends uploaded 文件 metadata in additional_kwargs.files
        after a successful upload. Each entry has: filename, size (bytes),
        路径 (virtual 路径), status.

        Args:
            消息: The human 消息 to inspect.
            uploads_dir: Physical uploads 目录 used to verify 文件 existence.
                         When provided, entries whose files no longer exist are skipped.

        Returns:
            List of 文件 dicts with virtual paths, or None if the field is absent or empty.
        """
        kwargs_files = (message.additional_kwargs or {}).get("files")
        if not isinstance(kwargs_files, list) or not kwargs_files:
            return None

        files = []
        for f in kwargs_files:
            if not isinstance(f, dict):
                continue
            filename = f.get("filename") or ""
            if not filename or Path(filename).name != filename:
                continue
            if uploads_dir is not None and not (uploads_dir / filename).is_file():
                continue
            files.append(
                {
                    "filename": filename,
                    "size": int(f.get("size") or 0),
                    "path": f"/mnt/user-data/uploads/{filename}",
                    "extension": Path(filename).suffix,
                }
            )
        return files if files else None

    @override
    def before_agent(self, state: UploadsMiddlewareState, runtime: Runtime) -> dict | None:
        """Inject uploaded files information before 代理 execution.

        New files come from the 当前 消息's additional_kwargs.files.
        Historical files are scanned from the 线程's uploads 目录,
        excluding the 新建 ones.

        Prepends <uploaded_files> context to the 最后 human 消息 content.
        The original additional_kwargs (including files metadata) is preserved
        on the updated 消息 so the 前端 can read it from the stream.

        Args:
            状态: Current 代理 状态.
            runtime: Runtime context containing thread_id.

        Returns:
            状态 updates including uploaded files 列表.
        """
        messages = list(state.get("messages", []))
        if not messages:
            return None

        last_message_index = len(messages) - 1
        last_message = messages[last_message_index]

        if not isinstance(last_message, HumanMessage):
            return None

        #    Resolve uploads 目录 对于 existence checks


        thread_id = runtime.context.get("thread_id")
        uploads_dir = self._paths.sandbox_uploads_dir(thread_id) if thread_id else None

        #    Get newly uploaded files from the 当前 消息's additional_kwargs.files


        new_files = self._files_from_kwargs(last_message, uploads_dir) or []

        #    Collect historical files from the uploads 目录 (all except the 新建 ones)


        new_filenames = {f["filename"] for f in new_files}
        historical_files: list[dict] = []
        if uploads_dir and uploads_dir.exists():
            for file_path in sorted(uploads_dir.iterdir()):
                if file_path.is_file() and file_path.name not in new_filenames:
                    stat = file_path.stat()
                    historical_files.append(
                        {
                            "filename": file_path.name,
                            "size": stat.st_size,
                            "path": f"/mnt/user-data/uploads/{file_path.name}",
                            "extension": file_path.suffix,
                        }
                    )

        if not new_files and not historical_files:
            return None

        logger.debug(f"New files: {[f['filename'] for f in new_files]}, historical: {[f['filename'] for f in historical_files]}")

        #    Create files 消息 and prepend to the 最后 human 消息 content


        files_message = self._create_files_message(new_files, historical_files)

        #    Extract original content - 处理 both 字符串 and 列表 formats


        original_content = ""
        if isinstance(last_message.content, str):
            original_content = last_message.content
        elif isinstance(last_message.content, list):
            text_parts = []
            for block in last_message.content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text_parts.append(block.get("text", ""))
            original_content = "\n".join(text_parts)

        #    Create 新建 消息 with combined content.


        #    Preserve additional_kwargs (including files metadata) so the 前端


        #    can read structured 文件 信息 from the streamed 消息.


        updated_message = HumanMessage(
            content=f"{files_message}\n\n{original_content}",
            id=last_message.id,
            additional_kwargs=last_message.additional_kwargs,
        )

        messages[last_message_index] = updated_message

        return {
            "uploaded_files": new_files,
            "messages": messages,
        }
