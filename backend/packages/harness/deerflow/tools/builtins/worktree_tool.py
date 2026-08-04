import asyncio
import re
import shlex
from pathlib import Path

from langchain_core.tools import tool

from deerflow.runtime.user_context import resolve_runtime_user_id
from deerflow.sandbox.tools import ensure_sandbox_initialized_async, is_local_sandbox
from deerflow.task_graph.factory import create_task_graph
from deerflow.tools.types import Runtime

VALID_WORKTREE_NAME = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def validate_worktree_name(name: str) -> None:
    """校验 Worktree 名称只能作为单个安全目录名使用。"""
    if name in {"", ".", ".."} or VALID_WORKTREE_NAME.fullmatch(name) is None:
        raise ValueError("invalid worktree name")


def _runtime_thread_id(runtime: Runtime) -> str:
    context = runtime.context or {}
    thread_id = context.get("thread_id")
    if thread_id is None:
        thread_id = runtime.config.get("configurable", {}).get("thread_id")
    if thread_id is None:
        raise ValueError("thread_id is required")
    return thread_id


def _resolve_repository(repository_path: str) -> Path:
    """解析用户本次选择的本地仓库绝对路径。"""
    requested = Path(repository_path)
    if not requested.is_absolute():
        raise ValueError("repository_path must be an absolute host path")
    resolved_repository = requested.resolve()
    if not resolved_repository.is_dir():
        raise FileNotFoundError(f"repository_path does not exist or is not a directory: {repository_path}")
    return resolved_repository


async def _ensure_worktrees_ignored(sandbox, repository_path: str) -> None:
    """把 Worktree 根目录加入目标仓库的本地排除文件。"""
    quoted_repository = shlex.quote(repository_path)
    exclude_path_output = await asyncio.to_thread(
        sandbox.execute_command,
        f"git -C {quoted_repository} rev-parse --path-format=absolute --git-path info/exclude",
    )
    exclude_path = exclude_path_output.strip()
    if not exclude_path or "\n" in exclude_path:
        actual = exclude_path or "<empty>"
        raise RuntimeError(f"failed to resolve Git info/exclude path: expected one path, got {actual!r}")

    try:
        existing = await asyncio.to_thread(sandbox.read_file, exclude_path)
    except OSError:
        existing = ""
    if ".worktrees/" in {line.strip() for line in existing.splitlines()}:
        return

    separator = "" if not existing or existing.endswith("\n") else "\n"
    await asyncio.to_thread(
        sandbox.write_file,
        exclude_path,
        f"{separator}.worktrees/\n",
        True,
    )


@tool("create_coding_worktree", parse_docstring=True)
async def create_coding_worktree(repository_path: str, name: str, task_ids: list[str], runtime: Runtime) -> str:
    """在用户本次选择的本地目标仓库中创建独立 Git Worktree，并绑定持久化任务。

    Args:
        repository_path: 用户本次要修改的本地 Git 仓库绝对路径，可以位于任意磁盘。
        name: Worktree 的安全单段名称，同时用于生成 ``coding/{name}`` 分支。
        task_ids: 需要共享该 Worktree 的持久化 CodingTask ID 列表。
    """
    validate_worktree_name(name)
    if not task_ids:
        raise ValueError("task_ids must not be empty")

    thread_id = _runtime_thread_id(runtime)
    sandbox = await ensure_sandbox_initialized_async(runtime)
    if not is_local_sandbox(runtime):
        raise RuntimeError("host repository worktrees currently require LocalSandboxProvider")

    repository = _resolve_repository(repository_path)
    worktree = repository / ".worktrees" / name
    host_repository = str(repository)
    host_worktree = str(worktree)
    command_repository = repository.as_posix()
    command_worktree = worktree.as_posix()
    branch = f"coding/{name}"
    quoted_repository = shlex.quote(command_repository)
    quoted_worktree = shlex.quote(command_worktree)

    workspace_check = await asyncio.to_thread(
        sandbox.execute_command,
        f"git -C {quoted_repository} rev-parse --is-inside-work-tree",
    )
    workspace_result = workspace_check.strip()
    if workspace_result != "true":
        actual = workspace_result or "<empty>"
        raise RuntimeError(f"target repository is not a Git repository: expected 'true', got {actual!r}")

    await _ensure_worktrees_ignored(sandbox, command_repository)
    create_output = await asyncio.to_thread(
        sandbox.execute_command,
        f"git -C {quoted_repository} worktree add -b {branch} {quoted_worktree} HEAD",
    )
    worktree_check = await asyncio.to_thread(
        sandbox.execute_command,
        f"git -C {quoted_worktree} rev-parse --is-inside-work-tree",
    )
    worktree_branch = await asyncio.to_thread(
        sandbox.execute_command,
        f"git -C {quoted_worktree} branch --show-current",
    )
    if worktree_check.strip() != "true" or worktree_branch.strip() != branch:
        create_detail = create_output.strip() or "<empty>"
        raise RuntimeError(
            f"worktree verification failed: expected path={host_worktree!r}, branch={branch!r}; actual inside-work-tree={worktree_check.strip()!r}, branch={worktree_branch.strip()!r}; git worktree add output={create_detail!r}"
        )

    user_id = resolve_runtime_user_id(runtime)
    graph = create_task_graph(thread_id, user_id=user_id)
    await asyncio.to_thread(graph.bind_worktree, task_ids, host_worktree)

    return f"Created coding worktree '{name}' for {host_repository} at {host_worktree} on branch {branch}; bound {len(task_ids)} tasks"
