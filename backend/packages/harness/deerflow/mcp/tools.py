"""Load MCP tools using langchain-mcp-adapters with stdio session pooling."""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Iterable, Mapping
from datetime import timedelta
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from langchain_core.tools import BaseTool, StructuredTool
from langgraph.config import get_config

from deerflow.config.extensions_config import ExtensionsConfig, McpServerConfig, resolve_effective_mcp_routing
from deerflow.config.paths import VIRTUAL_PATH_PREFIX, Paths, get_paths
from deerflow.constants import DEFAULT_MCP_SESSION_INIT_TIMEOUT, MCP_TMP_SUBDIR
from deerflow.mcp.client import build_servers_config
from deerflow.mcp.interceptors import build_mcp_tool_interceptors
from deerflow.mcp.oauth import build_oauth_tool_interceptor, get_initial_oauth_headers
from deerflow.mcp.session_pool import get_session_pool
from deerflow.mcp.tasks import ORDINARY_MCP_TASK_DRIVER, TaskSubmitRequest
from deerflow.mcp.tasks.runtime import (
    McpTaskConfigurationError,
    get_mcp_task_submitter,
    validate_mcp_task_config_snapshot,
)
from deerflow.reflection import resolve_variable
from deerflow.runtime.user_context import resolve_runtime_user_id
from deerflow.tools.mcp_metadata import tag_mcp_routing, tag_mcp_tool
from deerflow.tools.sync import make_sync_tool_wrapper
from deerflow.tools.types import Runtime

logger = logging.getLogger(__name__)

# MCP tool names arrive verbatim from external (potentially hostile/compromised)
# servers. A tool name is only ever a function identifier: the provider's
# function-calling API validates it against this same charset at bind time. But
# deferred (tool_search) MCP tools are withheld from binding, so that provider
# check never runs on their names — they only ever live in the system-prompt
# string, where a crafted name (newlines, markdown, angle brackets) could forge
# framework prompt structure. Canonicalizing at the load boundary constrains
# both bound and deferred names to the same safe identifier charset, mirroring
# the load-time validation skill names get (skills/storage/skill_storage.py).
_VALID_MCP_TOOL_NAME = re.compile(r"^[A-Za-z0-9_-]+$")

# Matches local-file references embedded in free text returned by an MCP server.
# Some servers (notably Playwright's ``browser_take_screenshot``) report saved
# files only as text/markdown links rather than ``ResourceLink`` blocks. Those
# references may be absolute paths, ``file://`` URIs, or paths relative to the
# server process cwd (e.g. ``temp/page.yml``, ``./shot.png``). Each match is
# only rewritten when it resolves to an existing file inside the thread's
# user-data tree, so an over-eager match is harmless (left untouched).
_LOCAL_PATH_IN_TEXT_RE = re.compile(r"(?:file://)?/[^\s'\"<>|*?]+|(?:\.{0,2}/|[\w.-]+/)[^\s'\"<>|*?]+")

# Trailing characters that are punctuation/markup rather than part of a path.
_TEXT_PATH_TRAILING_CHARS = ".,;:!?)]}>\"'`"

_FILE_SNAPSHOT = dict[Path, tuple[int, int]]


def _local_path_from_uri(uri: str, *, base_dir: Path | None = None) -> Path | None:
    """Return an absolute local filesystem ``Path`` if *uri* points to a local
    file, otherwise ``None``.

    Accepts bare paths and ``file://`` URIs. Remote URIs
    (``http``/``https``/``data``/...) return ``None`` so the caller leaves them
    untouched. Relative paths are resolved only when *base_dir* is supplied.
    """
    if not uri:
        return None
    try:
        parsed = urlparse(uri)
    except ValueError:
        return None
    if parsed.scheme == "file":
        raw = unquote(parsed.path)
    elif parsed.scheme == "":
        raw = uri
    else:
        return None
    if not raw:
        return None
    path = Path(raw)
    if not path.is_absolute():
        if base_dir is None:
            return None
        path = base_dir / path
    return path


def _local_uri_to_virtual_path(
    uri: str,
    *,
    thread_id: str,
    user_id: str,
    source_base_dir: Path | None = None,
) -> str | None:
    """Translate a local file reference into its ``/mnt/user-data/...`` virtual path.

    Stdio MCP servers run with their cwd and temp dir pinned inside the thread's
    mounted user-data tree (see :func:`_make_session_pool_tool`), so the files
    they produce already live somewhere the sandbox/artifact API can serve — the
    only thing missing is the virtual prefix the rest of DeerFlow addresses them
    by. This performs that purely deterministic host→virtual mapping: no copy, no
    trusted-root list, and no exposure of files outside the thread's own tree.

    Returns ``None`` (so the caller leaves the reference untouched) when the URI
    is remote, cannot be resolved, points outside this thread's user-data tree,
    or does not name an existing file. Relative references are resolved against
    *source_base_dir* (the server's cwd).
    """
    src = _local_path_from_uri(uri, base_dir=source_base_dir)
    if src is None:
        return None

    try:
        real = src.resolve()
        if not real.is_file():
            return None
    except OSError:
        return None

    try:
        user_data_root = get_paths().sandbox_user_data_dir(thread_id, user_id=user_id).resolve()
    except OSError:
        return None

    try:
        relative = real.relative_to(user_data_root)
    except ValueError:
        # The file lives outside this thread's user-data mount; we cannot
        # express it as a virtual path, so leave the original reference as-is.
        logger.debug("MCP path rewrite skipped outside user-data tree: %s", real)
        return None

    virtual_path = f"{VIRTUAL_PATH_PREFIX}/{relative.as_posix()}"
    logger.debug("MCP path rewrite: %s -> %s", real, virtual_path)
    return virtual_path


def _snapshot_workspace_files(root: Path) -> _FILE_SNAPSHOT:
    """Return a lightweight snapshot of regular files under *root*."""
    snapshot: _FILE_SNAPSHOT = {}
    if not root.exists():
        return snapshot

    try:
        candidates = root.rglob("*")
        for path in candidates:
            try:
                stat = path.stat()
            except OSError:
                continue
            if path.is_file():
                snapshot[path] = (stat.st_mtime_ns, stat.st_size)
    except OSError:
        return snapshot
    return snapshot


def _changed_workspace_files(root: Path, before: _FILE_SNAPSHOT) -> list[Path]:
    """Return files under *root* that were created or modified since *before*."""
    after = _snapshot_workspace_files(root)
    return [path for path, signature in after.items() if before.get(path) != signature]


def _prepare_stdio_workspace(paths: Paths, *, thread_id: str, user_id: str) -> tuple[Path, Path, _FILE_SNAPSHOT]:
    """Prepare the thread workspace for a pinned stdio MCP subprocess.

    Bundles all the synchronous filesystem work (dir creation, temp-dir prep,
    and the pre-call snapshot) into one helper so the caller can run it off the
    event loop via :func:`asyncio.to_thread`. Returns the workspace cwd, the
    pinned temp dir, and the pre-call file snapshot.
    """
    paths.ensure_thread_dirs(thread_id, user_id=user_id)
    source_base_dir = paths.sandbox_work_dir(thread_id, user_id=user_id)
    tmp_dir = source_base_dir / MCP_TMP_SUBDIR
    try:
        tmp_dir.mkdir(parents=True, exist_ok=True)
        tmp_dir.chmod(0o700)
    except OSError:
        logger.warning("Failed to prepare MCP temp dir: %s", tmp_dir, exc_info=True)
    before_files = _snapshot_workspace_files(source_base_dir)
    return source_base_dir, tmp_dir, before_files


def _result_has_text_content(call_tool_result: Any) -> bool:
    """Return ``True`` when the MCP result carries any text content.

    The after-call snapshot diff only feeds bare-filename correlation in free
    text. When the result has no text blocks there is nothing to rewrite, so the
    caller can skip the second recursive walk entirely.
    """
    from mcp.types import EmbeddedResource, TextContent, TextResourceContents

    content = getattr(call_tool_result, "content", None)
    if not content:
        return False
    for item in content:
        if isinstance(item, TextContent):
            return True
        if isinstance(item, EmbeddedResource) and isinstance(item.resource, TextResourceContents):
            return True
    return False


def _rewrite_unique_bare_filenames(
    text: str,
    *,
    changed_files: Iterable[Path],
    thread_id: str,
    user_id: str,
    source_base_dir: Path | None = None,
) -> str:
    """Rewrite bare filenames only when this call produced a unique match.

    A response like ``Saved as page-2026.yml`` is not structurally a path. The
    only safe way to interpret it is to correlate the filename with files
    created/modified by this exact tool call, and rewrite only when the basename
    maps to exactly one file inside this thread's mounted user-data tree.
    """
    candidates: dict[str, list[str]] = {}
    for path in changed_files:
        virtual_path = _local_uri_to_virtual_path(
            str(path),
            thread_id=thread_id,
            user_id=user_id,
            source_base_dir=source_base_dir,
        )
        if virtual_path is None:
            continue
        candidates.setdefault(path.name, []).append(virtual_path)

    unique = {name: paths[0] for name, paths in candidates.items() if len(set(paths)) == 1}
    if not unique:
        if candidates:
            logger.debug("MCP bare filename rewrite skipped: no unique candidate in %s", sorted(candidates))
        else:
            logger.debug("MCP bare filename rewrite skipped: no snapshot candidates")
        return text

    rewritten = text
    for name in sorted(unique, key=len, reverse=True):
        # Do not rewrite inside longer paths/words. A final sentence period is
        # allowed, but ".bak" or another path segment is not.
        pattern = re.compile(rf"(?<![\w./-]){re.escape(name)}(?!(?:[\w/-]|\.[\w]))")
        rewritten_text, count = pattern.subn(unique[name], rewritten)
        if count:
            logger.debug("MCP bare filename rewrite: %s -> %s", name, unique[name])
        rewritten = rewritten_text
    return rewritten


def _rewrite_local_paths_in_text(
    text: str,
    *,
    thread_id: str,
    user_id: str,
    source_base_dir: Path | None = None,
    changed_files: Iterable[Path] | None = None,
) -> str:
    """Best-effort rewrite of local file references found in free text.

    Some MCP servers (notably Playwright's ``browser_take_screenshot``) report
    the saved file only as free text — e.g. ``Took the screenshot and saved it
    as temp/page-2026.png`` — instead of a ``ResourceLink``. Free text is not a
    reliable protocol, so this is deliberately conservative: every candidate
    token is handed to :func:`_local_uri_to_virtual_path`, which only rewrites
    it when it resolves to an existing file inside this thread's user-data tree.
    Tokens that are not real paths (or point elsewhere) are left exactly as they
    were, so an over-eager regex match has no harmful effect.
    """
    translated_by_source: dict[str, str | None] = {}

    def _replace(match: re.Match[str]) -> str:
        token = match.group(0)
        # A path can end a sentence ("saved as temp/a.png."); strip trailing
        # punctuation and restore it after the (possibly rewritten) path.
        stripped = token.rstrip(_TEXT_PATH_TRAILING_CHARS)
        trailing = token[len(stripped) :]
        if stripped not in translated_by_source:
            translated_by_source[stripped] = _local_uri_to_virtual_path(
                stripped,
                thread_id=thread_id,
                user_id=user_id,
                source_base_dir=source_base_dir,
            )
        rewritten = translated_by_source[stripped]
        if rewritten is None:
            return token
        return f"{rewritten}{trailing}"

    rewritten = _LOCAL_PATH_IN_TEXT_RE.sub(_replace, text)
    if changed_files is None:
        return rewritten
    return _rewrite_unique_bare_filenames(
        rewritten,
        changed_files=changed_files,
        thread_id=thread_id,
        user_id=user_id,
        source_base_dir=source_base_dir,
    )


def _extract_thread_id(runtime: Runtime | None) -> str:
    """Extract thread_id from the injected tool runtime or LangGraph config."""
    if runtime is not None:
        tid = runtime.context.get("thread_id") if runtime.context else None
        if tid is not None:
            return str(tid)
        config = runtime.config or {}
        tid = config.get("configurable", {}).get("thread_id")
        if tid is not None:
            return str(tid)

    try:
        tid = get_config().get("configurable", {}).get("thread_id")
        return str(tid) if tid is not None else "default"
    except RuntimeError:
        return "default"


def _convert_call_tool_result(
    call_tool_result: Any,
    *,
    thread_id: str | None = None,
    user_id: str | None = None,
    source_base_dir: Path | None = None,
    changed_files: Iterable[Path] | None = None,
) -> Any:
    """Convert an MCP CallToolResult to the LangChain ``content_and_artifact`` format.

    Implements the same conversion logic as the adapter without relying on
    the private ``langchain_mcp_adapters.tools._convert_call_tool_result`` symbol.

    When ``thread_id`` and ``user_id`` are provided, local files referenced by
    ``ResourceLink`` blocks or plain text (e.g. screenshots saved by Playwright
    MCP) have their references translated from the host path to the
    ``/mnt/user-data/...`` virtual path so they can be resolved by the sandbox
    and artifact API. The files themselves are not copied — stdio servers run
    with their cwd/temp pinned inside the mounted tree, so they already live in
    a servable location. Remote URIs and files outside the thread's user-data
    tree are left untouched.
    """
    from langchain_core.messages import ToolMessage
    from langchain_core.messages.content import create_file_block, create_image_block, create_text_block
    from langchain_core.tools import ToolException
    from mcp.types import EmbeddedResource, ImageContent, ResourceLink, TextContent, TextResourceContents

    # Pass ToolMessage through directly (interceptor short-circuit).
    if isinstance(call_tool_result, ToolMessage):
        return call_tool_result, None

    # Pass LangGraph Command through directly when langgraph is installed.
    try:
        from langgraph.types import Command

        if isinstance(call_tool_result, Command):
            return call_tool_result, None
    except ImportError:
        # langgraph is optional; if unavailable, continue with standard MCP content conversion.
        pass

    def _resolve_link_url(uri: str) -> str:
        if thread_id is None or user_id is None:
            return uri
        rewritten = _local_uri_to_virtual_path(uri, thread_id=thread_id, user_id=user_id, source_base_dir=source_base_dir)
        return rewritten if rewritten is not None else uri

    def _resolve_text(text: str) -> str:
        # Servers like Playwright report saved files only as plain text, with no
        # ResourceLink to hook into. Scan the text for local paths and translate
        # them so the produced files are readable through the sandbox/artifact API.
        if thread_id is None or user_id is None:
            return text
        return _rewrite_local_paths_in_text(
            text,
            thread_id=thread_id,
            user_id=user_id,
            source_base_dir=source_base_dir,
            changed_files=changed_files,
        )

    # Convert MCP content blocks to LangChain content blocks.
    lc_content = []
    for item in call_tool_result.content:
        if isinstance(item, TextContent):
            lc_content.append(create_text_block(text=_resolve_text(item.text)))
        elif isinstance(item, ImageContent):
            lc_content.append(create_image_block(base64=item.data, mime_type=item.mimeType))
        elif isinstance(item, ResourceLink):
            mime = item.mimeType or None
            url = _resolve_link_url(str(item.uri))
            if mime and mime.startswith("image/"):
                lc_content.append(create_image_block(url=url, mime_type=mime))
            else:
                lc_content.append(create_file_block(url=url, mime_type=mime))
        elif isinstance(item, EmbeddedResource):
            from mcp.types import BlobResourceContents

            res = item.resource
            if isinstance(res, TextResourceContents):
                lc_content.append(create_text_block(text=_resolve_text(res.text)))
            elif isinstance(res, BlobResourceContents):
                mime = res.mimeType or None
                if mime and mime.startswith("image/"):
                    lc_content.append(create_image_block(base64=res.blob, mime_type=mime))
                else:
                    lc_content.append(create_file_block(base64=res.blob, mime_type=mime))
            else:
                lc_content.append(create_text_block(text=str(res)))
        else:
            lc_content.append(create_text_block(text=str(item)))

    if call_tool_result.isError:
        error_parts = [item["text"] for item in lc_content if isinstance(item, dict) and item.get("type") == "text"]
        raise ToolException("\n".join(error_parts) if error_parts else str(lc_content))

    artifact = None
    if call_tool_result.structuredContent is not None:
        artifact = {"structured_content": call_tool_result.structuredContent}

    return lc_content, artifact


def _resolve_session_init_timeout(server_cfg: Any) -> float | None:
    """Return the effective session-init timeout for *server_cfg*.

    ``None`` (an explicit opt-out) stays ``None``. Any other non-numeric value
    falls back to the default rather than being passed to ``asyncio.wait_for``
    (which would raise on it) or silently disabling the bound: pydantic
    guarantees a float for real configs, but configs built with mocks in tests
    can supply anything, and the fallback keeps the hang-protection in place.
    """
    value = server_cfg.session_init_timeout if server_cfg is not None else DEFAULT_MCP_SESSION_INIT_TIMEOUT
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return DEFAULT_MCP_SESSION_INIT_TIMEOUT
    return float(value)


def _make_session_pool_tool(
    tool: BaseTool,
    server_name: str,
    connection: dict[str, Any],
    tool_interceptors: list[Any] | None = None,
    tool_call_timeout: float | None = None,
    session_init_timeout: float | None = None,
    tool_name_prefix: bool = True,
) -> BaseTool:
    """Wrap an MCP tool so it reuses a persistent session from the pool.

    Replaces the per-call session creation with pool-managed sessions scoped
    by ``(server_name, user_id:thread_id)``.  This ensures stateful MCP servers
    (e.g. Playwright) keep their state across tool calls within the same thread
    while staying isolated per user.

    The configured ``tool_interceptors`` (OAuth, custom) are preserved and
    applied on every call before invoking the pooled session.
    """
    # Strip only prefixes added by the adapter. An unprefixed server may expose
    # a tool whose own name happens to start with ``<server_name>_``.
    original_name = tool.name
    prefix = f"{server_name}_"
    if tool_name_prefix and original_name.startswith(prefix):
        original_name = original_name[len(prefix) :]

    pool = get_session_pool()

    async def call_with_persistent_session(
        runtime: Runtime | None = None,
        **arguments: Any,
    ) -> Any:
        thread_id = _extract_thread_id(runtime)
        user_id = resolve_runtime_user_id(runtime)
        # Scope the pooled session by user *and* thread. Filesystem isolation is
        # per-(user_id, thread_id), so a thread_id alone could otherwise let two
        # users with a colliding thread_id share one stateful MCP session.
        scope_key = f"{user_id}:{thread_id}"
        session_connection = dict(connection)
        # cwd/temp pinning and the workspace snapshot only matter for stdio
        # servers, which run as local subprocesses writing to a real filesystem.
        # SSE/HTTP servers have no local cwd to pin, so skip the filesystem work
        # entirely for them (avoids needless dir creation and recursive walks).
        is_stdio = session_connection.get("transport", "stdio") == "stdio"
        source_base_dir: Path | None = None
        process_cwd: Path | None = None
        before_files: _FILE_SNAPSHOT | None = None
        if is_stdio:
            paths = get_paths()
            # Bundle the synchronous filesystem prep (dir creation, temp-dir
            # setup, pre-call snapshot) and run it off the event loop — the
            # snapshot walks the whole workspace and would otherwise block.
            source_base_dir, tmp_dir, before_files = await asyncio.to_thread(_prepare_stdio_workspace, paths, thread_id=thread_id, user_id=user_id)
            # Stdio MCP servers resolve relative output links against their
            # process cwd. Keep that cwd inside the thread's mounted user-data
            # tree so files produced by tools like Playwright land where the
            # sandbox/artifact API can serve them and their references can be
            # translated to virtual paths.
            configured_cwd = session_connection.get("cwd", str(source_base_dir))
            session_connection["cwd"] = str(configured_cwd)
            process_cwd = Path(configured_cwd)
            # Pin the subprocess temp dir under the same mounted tree. Tools that
            # default to the OS temp dir (Node's os.tmpdir(), Python's tempfile,
            # many CLIs) then write inside user-data instead of an unreachable
            # host path — the tool-agnostic counterpart to fixing the cwd. Merge
            # rather than replace any operator-provided env.
            session_env = dict(session_connection.get("env") or {})
            session_env.setdefault("TMPDIR", str(tmp_dir))
            session_env.setdefault("TMP", str(tmp_dir))
            session_env.setdefault("TEMP", str(tmp_dir))
            session_connection["env"] = session_env
        if session_init_timeout is not None:
            # Cancellation here is safe: MCPSessionPool.get_session owns the
            # teardown of a session stuck mid-creation (it signals close and
            # waits for the owner task's __aexit__ to run in its own task),
            # so a hung server cannot leak a session or block the turn.
            try:
                session = await asyncio.wait_for(
                    pool.get_session(server_name, scope_key, session_connection),
                    timeout=session_init_timeout,
                )
            except TimeoutError:
                # Surface the timeout at the same log level as discovery
                # timeouts: the tool call still fails with a TimeoutError the
                # model can react to, but operators need the WARNING to
                # diagnose tool-call failures caused by hung MCP sessions.
                logger.warning(
                    "MCP session initialization for server '%s' timed out after %.1fs",
                    server_name,
                    session_init_timeout,
                )
                raise
        else:
            session = await pool.get_session(server_name, scope_key, session_connection)

        # Build common call_tool kwargs once — only add keys when needed so
        # existing call-sites that assert on exact arguments are not affected.
        call_kwargs: dict[str, Any] = {}
        if tool_call_timeout:
            call_kwargs["read_timeout_seconds"] = timedelta(seconds=tool_call_timeout)

        if tool_interceptors:
            from langchain_mcp_adapters.interceptors import MCPToolCallRequest

            async def base_handler(request: MCPToolCallRequest) -> Any:
                # Preserve interceptor-injected headers for stdio MCP calls by
                # forwarding them through MCP call meta.
                kwargs = dict(call_kwargs)
                if request.headers:
                    if isinstance(request.headers, Mapping):
                        kwargs["meta"] = {"headers": dict(request.headers)}
                    else:
                        logger.warning("Ignoring MCP interceptor headers with unsupported type: %s", type(request.headers).__name__)
                return await session.call_tool(
                    request.name,
                    request.args,
                    **kwargs,
                )

            handler = base_handler
            for interceptor in reversed(tool_interceptors):
                outer = handler

                async def wrapped(req: Any, _i: Any = interceptor, _h: Any = outer) -> Any:
                    return await _i(req, _h)

                handler = wrapped

            request = MCPToolCallRequest(
                name=original_name,
                args=arguments,
                server_name=server_name,
                runtime=runtime,
            )
            call_tool_result = await handler(request)
        else:
            call_tool_result = await session.call_tool(
                original_name,
                arguments,
                **call_kwargs,
            )

        # The after-call snapshot diff only feeds bare-filename correlation in
        # free text, so skip the second recursive walk when there is no text
        # content to rewrite. Both the diff and the per-token path resolution
        # inside _convert_call_tool_result touch the filesystem, so run them off
        # the event loop.
        changed_files: list[Path] | None = None
        if is_stdio and before_files is not None and _result_has_text_content(call_tool_result):
            changed_files = await asyncio.to_thread(_changed_workspace_files, source_base_dir, before_files)
        return await asyncio.to_thread(
            _convert_call_tool_result,
            call_tool_result,
            thread_id=thread_id,
            user_id=user_id,
            source_base_dir=process_cwd,
            changed_files=changed_files,
        )

    return StructuredTool(
        name=tool.name,
        description=tool.description,
        args_schema=tool.args_schema,
        coroutine=call_with_persistent_session,
        response_format="content_and_artifact",
        metadata=tool.metadata,
    )


def _raw_mcp_tool_name(
    tool: BaseTool,
    *,
    server_name: str,
    tool_name_prefix: bool,
) -> str:
    prefix = f"{server_name}_"
    if tool_name_prefix and tool.name.startswith(prefix):
        return tool.name[len(prefix) :]
    return tool.name


def _make_background_submit_tool(
    tool: BaseTool,
    *,
    server_name: str,
    task_name: str,
    submit_tool: str,
    status_tool: str,
    cancel_tool: str,
) -> BaseTool:
    background_contract = f"Submitted as durable background task {task_name!r}; returns a DeerFlow task ID immediately and status polling is handled automatically."

    async def submit_in_background(
        runtime: Runtime | None = None,
        **arguments: Any,
    ) -> dict[str, Any]:
        submitter = get_mcp_task_submitter()
        thread_id = _extract_thread_id(runtime)
        user_id = resolve_runtime_user_id(runtime)
        context = runtime.context if runtime is not None and runtime.context else {}
        run_id = context.get("run_id")
        tool_call_id = getattr(runtime, "tool_call_id", None) if runtime is not None else None
        created = await submitter.submit(
            driver_name=ORDINARY_MCP_TASK_DRIVER,
            request=TaskSubmitRequest(
                user_id=user_id,
                thread_id=thread_id,
                run_id=str(run_id) if run_id is not None else None,
                tool_call_id=str(tool_call_id) if tool_call_id is not None else None,
                server_name=server_name,
                task_name=task_name,
                arguments=arguments,
                driver_data={
                    "submit_tool": submit_tool,
                    "status_tool": status_tool,
                    "cancel_tool": cancel_tool,
                },
            ),
        )
        return {
            "task_id": created["id"],
            "task_name": task_name,
            "status": created["status"],
            "message": "Task is running in the background.",
        }

    return StructuredTool(
        name=tool.name,
        description=(f"{tool.description}\n\n{background_contract}" if tool.description else background_contract),
        args_schema=tool.args_schema,
        coroutine=submit_in_background,
        metadata=tool.metadata,
    )


def _configure_task_tools_for_server(
    tools: list[BaseTool],
    *,
    server_name: str,
    server_config: McpServerConfig,
    tool_name_prefix: bool,
) -> list[BaseTool]:
    """Hide driver-only tools and replace submit with a durable wrapper."""
    if not server_config.task_toolsets:
        return tools

    by_raw_name = {
        _raw_mcp_tool_name(
            tool,
            server_name=server_name,
            tool_name_prefix=tool_name_prefix,
        ): tool
        for tool in tools
    }
    expected = {
        raw_name
        for toolset in server_config.task_toolsets
        for raw_name in (
            toolset.submit_tool,
            toolset.status_tool,
            toolset.cancel_tool,
        )
    }
    missing = sorted(expected - by_raw_name.keys())
    if missing:
        raise McpTaskConfigurationError(f"MCP server {server_name!r} task_toolsets reference missing raw tool(s): {', '.join(missing)}")

    hidden = {raw_name for toolset in server_config.task_toolsets for raw_name in (toolset.status_tool, toolset.cancel_tool)}
    submit_by_name = {toolset.submit_tool: toolset for toolset in server_config.task_toolsets}
    configured: list[BaseTool] = []
    for tool in tools:
        raw_name = _raw_mcp_tool_name(
            tool,
            server_name=server_name,
            tool_name_prefix=tool_name_prefix,
        )
        if raw_name in hidden:
            continue
        toolset = submit_by_name.get(raw_name)
        if toolset is None:
            configured.append(tool)
            continue
        configured.append(
            _make_background_submit_tool(
                tool,
                server_name=server_name,
                task_name=toolset.name,
                submit_tool=toolset.submit_tool,
                status_tool=toolset.status_tool,
                cancel_tool=toolset.cancel_tool,
            )
        )
    return configured


async def get_mcp_tools() -> list[BaseTool]:
    """Get all tools from enabled MCP servers.

    Tools using stdio transport are wrapped with persistent-session logic so
    consecutive calls within the same thread reuse the same MCP session.
    HTTP/SSE tools are returned unwrapped to avoid cross-task TaskGroup
    cleanup errors.

    Returns:
        List of LangChain tools from all enabled MCP servers.
    """
    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient
        from langchain_mcp_adapters.tools import load_mcp_tools
    except ImportError:
        logger.warning("langchain-mcp-adapters not installed. Install it to enable MCP tools: pip install langchain-mcp-adapters")
        return []

    # NOTE: We use ExtensionsConfig.from_file() instead of get_extensions_config()
    # to always read the latest configuration from disk. This ensures that changes
    # made through the Gateway API (which runs in a separate process) are immediately
    # reflected when initializing MCP tools.
    extensions_config = ExtensionsConfig.from_file()
    validate_mcp_task_config_snapshot(extensions_config)
    servers_config = build_servers_config(extensions_config)

    if not servers_config:
        logger.info("No enabled MCP servers configured")
        return []

    try:
        # Create the multi-server MCP client
        logger.info(f"Initializing MCP client with {len(servers_config)} server(s)")

        # Inject initial OAuth headers for server connections (tool discovery/session init)
        initial_oauth_headers = await get_initial_oauth_headers(extensions_config)
        for server_name, auth_header in initial_oauth_headers.items():
            if server_name not in servers_config:
                continue
            if servers_config[server_name].get("transport") in ("sse", "http"):
                existing_headers = dict(servers_config[server_name].get("headers", {}))
                existing_headers["Authorization"] = auth_header
                servers_config[server_name]["headers"] = existing_headers

        tool_interceptors = build_mcp_tool_interceptors(
            extensions_config,
            oauth_builder=build_oauth_tool_interceptor,
            resolver=resolve_variable,
            target_logger=logger,
        )

        client = MultiServerMCPClient(
            servers_config,
            tool_interceptors=tool_interceptors,
            tool_name_prefix=True,
        )

        async def load_server_tools(server_name: str) -> list[BaseTool]:
            try:
                server_cfg = extensions_config.mcp_servers.get(server_name)
                tool_name_prefix = server_cfg.tool_name_prefix if server_cfg is not None else True
                session_init_timeout = _resolve_session_init_timeout(server_cfg)
                if tool_name_prefix:
                    discovery = client.get_tools(server_name=server_name)
                else:
                    discovery = load_mcp_tools(
                        None,
                        connection=servers_config[server_name],
                        callbacks=client.callbacks,
                        server_name=server_name,
                        tool_interceptors=client.tool_interceptors,
                        tool_name_prefix=False,
                    )
                if session_init_timeout is not None:
                    # Timeout tool discovery (subprocess spawn + initialize +
                    # tools/list) so a hung stdio server cannot block agent
                    # construction indefinitely. Per-server because the gather
                    # below runs each server independently — one slow server
                    # must not prevent the others from contributing tools.
                    #
                    # Cancellation here is safe: discovery runs inside the
                    # adapter's nested async context managers (load_mcp_tools →
                    # create_session → _create_stdio_session → stdio_client),
                    # and wait_for's CancelledError unwinds them. stdio_client's
                    # finally closes stdin, waits for a graceful exit, then
                    # escalates to _terminate_process_tree (SIGTERM→SIGKILL on
                    # POSIX, process-tree termination on Windows), so the npx
                    # subprocess and any children it spawned are reaped — no
                    # orphan processes accumulate across repeated timeouts.
                    try:
                        return await asyncio.wait_for(discovery, timeout=session_init_timeout)
                    except TimeoutError:
                        # Only our own bound is logged as "timed out": the
                        # branch condition guarantees the value is not None, so
                        # the %.1f format cannot fail. A TimeoutError raised by
                        # discovery itself (e.g. an internal SDK timeout on the
                        # opted-out path) falls through to the generic failure
                        # handler below instead.
                        logger.warning(
                            "Skipping MCP server '%s' after tool discovery timed out (%.1fs)",
                            server_name,
                            session_init_timeout,
                        )
                        return []
                return await discovery
            except Exception as e:
                logger.warning(
                    f"Skipping MCP server '{server_name}' after tool discovery failed: {e}",
                    exc_info=True,
                )
                return []

        # Get tools from each server independently so one broken MCP server does
        # not prevent healthy servers from contributing their tools.
        tools_by_server = await asyncio.gather(*(load_server_tools(name) for name in servers_config))
        tools = [tool for server_tools in tools_by_server for tool in server_tools]
        logger.info(f"Successfully loaded {len(tools)} tool(s) from MCP servers")

        # Wrap each tool with persistent-session logic.
        # Only pool stdio sessions. HTTP/SSE transports use anyio TaskGroups
        # internally which cannot be closed from a different async task, so
        # pooling them causes RuntimeError on cleanup (see #3203).
        wrapped_tools: list[BaseTool] = []
        # Route each tool by the server that actually produced it: tools_by_server[i]
        # corresponds to the i-th server in servers_config. Inferring the source server by
        # scanning servers_config for a name prefix is ambiguous when one server name is a
        # prefix of another (e.g. "web" vs "web_scraper" → "web_scraper_search".startswith(
        # "web_") matches "web" first), which pools the tool under the wrong server. Using the
        # source grouping makes routing exact even when a server opts out of name prefixing.
        for source_name, server_tools in zip(servers_config.keys(), tools_by_server, strict=True):
            transport = servers_config[source_name].get("transport", "stdio")
            server_cfg = extensions_config.mcp_servers.get(source_name)
            tool_name_prefix = server_cfg.tool_name_prefix if server_cfg is not None else True
            current_server_tools: list[BaseTool] = []
            for tool in server_tools:
                if not _VALID_MCP_TOOL_NAME.fullmatch(tool.name or ""):
                    logger.warning(
                        "Dropping MCP tool from server '%s' with invalid name %r: tool names must match %s. A name outside this charset cannot be bound as a function tool and could forge prompt structure when listed as a deferred tool.",
                        source_name,
                        tool.name,
                        _VALID_MCP_TOOL_NAME.pattern,
                    )
                    continue
                tag_mcp_tool(tool)
                prefix = f"{source_name}_"
                original_name = tool.name[len(prefix) :] if tool_name_prefix and tool.name.startswith(prefix) else tool.name
                routing = resolve_effective_mcp_routing(server_cfg, original_name)
                if routing.get("mode") != "off":
                    tag_mcp_routing(tool, routing)
                if transport == "stdio":
                    _timeout = server_cfg.tool_call_timeout if server_cfg else None
                    _init_timeout = _resolve_session_init_timeout(server_cfg)
                    current_server_tools.append(
                        _make_session_pool_tool(
                            tool,
                            source_name,
                            servers_config[source_name],
                            tool_interceptors,
                            tool_call_timeout=_timeout,
                            session_init_timeout=_init_timeout,
                            tool_name_prefix=tool_name_prefix,
                        )
                    )
                else:
                    if transport != "stdio" and server_cfg and server_cfg.tool_call_timeout is not None:
                        logger.warning(
                            "Ignoring tool_call_timeout for MCP server '%s' because transport '%s' is not stdio; configure HTTP/SSE transport-level timeouts instead.",
                            source_name,
                            transport,
                        )
                    current_server_tools.append(tool)

            if server_cfg is not None:
                current_server_tools = _configure_task_tools_for_server(
                    current_server_tools,
                    server_name=source_name,
                    server_config=server_cfg,
                    tool_name_prefix=tool_name_prefix,
                )
            wrapped_tools.extend(current_server_tools)

        # Patch tools to support sync invocation, as deerflow client streams synchronously
        for tool in wrapped_tools:
            if getattr(tool, "func", None) is None and getattr(tool, "coroutine", None) is not None:
                tool.func = make_sync_tool_wrapper(tool.coroutine, tool.name)

        return wrapped_tools

    except McpTaskConfigurationError:
        raise
    except Exception as e:
        logger.error(f"Failed to load MCP tools: {e}", exc_info=True)
        return []
