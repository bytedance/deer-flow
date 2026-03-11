import re
from pathlib import Path

from langchain.tools import ToolRuntime, tool
from langgraph.typing import ContextT

from src.agents.thread_state import ThreadDataState, ThreadState
from src.config.paths import VIRTUAL_PATH_PREFIX
from src.utils.runtime import get_thread_id
from src.sandbox.exceptions import (
    SandboxError,
    SandboxNotFoundError,
    SandboxRuntimeError,
)
from src.sandbox.sandbox import Sandbox
from src.sandbox.sandbox_provider import get_sandbox_provider
from src.storage import OUTPUTS_VIRTUAL_PREFIX, is_uploads_virtual_path, materialize_upload_to_local_cache, publish_output_file


def replace_virtual_path(path: str, thread_data: ThreadDataState | None) -> str:
    """Replace virtual /mnt/user-data paths with actual thread data paths.

    Mapping:
        /mnt/user-data/workspace/* -> thread_data['workspace_path']/*
        /mnt/user-data/uploads/* -> thread_data['uploads_path']/*
        /mnt/user-data/outputs/* -> thread_data['outputs_path']/*

    Args:
        path: The path that may contain virtual path prefix.
        thread_data: The thread data containing actual paths.

    Returns:
        The path with virtual prefix replaced by actual path.
    """
    if not path.startswith(VIRTUAL_PATH_PREFIX):
        return path

    if thread_data is None:
        return path

    # Map virtual subdirectories to thread_data keys
    path_mapping = {
        "workspace": thread_data.get("workspace_path"),
        "uploads": thread_data.get("uploads_path"),
        "outputs": thread_data.get("outputs_path"),
    }

    # Extract the subdirectory after /mnt/user-data/
    relative_path = path[len(VIRTUAL_PATH_PREFIX) :].lstrip("/")
    if not relative_path:
        return path

    # Find which subdirectory this path belongs to
    parts = relative_path.split("/", 1)
    subdir = parts[0]
    rest = parts[1] if len(parts) > 1 else ""

    actual_base = path_mapping.get(subdir)
    if actual_base is None:
        return path

    if rest:
        return f"{actual_base}/{rest}"
    return actual_base


def replace_virtual_paths_in_command(command: str, thread_data: ThreadDataState | None) -> str:
    """Replace all virtual /mnt/user-data paths in a command string.

    Args:
        command: The command string that may contain virtual paths.
        thread_data: The thread data containing actual paths.

    Returns:
        The command with all virtual paths replaced.
    """
    if VIRTUAL_PATH_PREFIX not in command:
        return command

    if thread_data is None:
        return command

    # Pattern to match /mnt/user-data followed by path characters
    pattern = re.compile(rf"{re.escape(VIRTUAL_PATH_PREFIX)}(/[^\s\"';&|<>()]*)?")

    def replace_match(match: re.Match) -> str:
        full_path = match.group(0)
        return replace_virtual_path(full_path, thread_data)

    return pattern.sub(replace_match, command)


def get_thread_data(runtime: ToolRuntime[ContextT, ThreadState] | None) -> ThreadDataState | None:
    """Extract thread_data from runtime state."""
    if runtime is None:
        return None
    if runtime.state is None:
        return None
    return runtime.state.get("thread_data")


def is_local_sandbox(runtime: ToolRuntime[ContextT, ThreadState] | None) -> bool:
    """Check if the current sandbox is a local sandbox.

    Path replacement is only needed for local sandbox since aio sandbox
    already has /mnt/user-data mounted in the container.
    """
    if runtime is None:
        return False
    if runtime.state is None:
        return False
    sandbox_state = runtime.state.get("sandbox")
    if sandbox_state is None:
        return False
    return sandbox_state.get("sandbox_id") == "local"


def sandbox_from_runtime(runtime: ToolRuntime[ContextT, ThreadState] | None = None) -> Sandbox:
    """Extract sandbox instance from tool runtime.

    DEPRECATED: Use ensure_sandbox_initialized() for lazy initialization support.
    This function assumes sandbox is already initialized and will raise error if not.

    Raises:
        SandboxRuntimeError: If runtime is not available or sandbox state is missing.
        SandboxNotFoundError: If sandbox with the given ID cannot be found.
    """
    if runtime is None:
        raise SandboxRuntimeError("Tool runtime not available")
    if runtime.state is None:
        raise SandboxRuntimeError("Tool runtime state not available")
    sandbox_state = runtime.state.get("sandbox")
    if sandbox_state is None:
        raise SandboxRuntimeError("Sandbox state not initialized in runtime")
    sandbox_id = sandbox_state.get("sandbox_id")
    if sandbox_id is None:
        raise SandboxRuntimeError("Sandbox ID not found in state")
    sandbox = get_sandbox_provider().get(sandbox_id)
    if sandbox is None:
        raise SandboxNotFoundError(f"Sandbox with ID '{sandbox_id}' not found", sandbox_id=sandbox_id)

    runtime.context["sandbox_id"] = sandbox_id  # Ensure sandbox_id is in context for downstream use
    return sandbox


def ensure_sandbox_initialized(runtime: ToolRuntime[ContextT, ThreadState] | None = None) -> Sandbox:
    """Ensure sandbox is initialized, acquiring lazily if needed.

    On first call, acquires a sandbox from the provider and stores it in runtime state.
    Subsequent calls return the existing sandbox.

    Thread-safety is guaranteed by the provider's internal locking mechanism.

    Args:
        runtime: Tool runtime containing state and context.

    Returns:
        Initialized sandbox instance.

    Raises:
        SandboxRuntimeError: If runtime is not available or thread_id is missing.
        SandboxNotFoundError: If sandbox acquisition fails.
    """
    if runtime is None:
        raise SandboxRuntimeError("Tool runtime not available")

    if runtime.state is None:
        raise SandboxRuntimeError("Tool runtime state not available")

    # Check if sandbox already exists in state
    sandbox_state = runtime.state.get("sandbox")
    if sandbox_state is not None:
        sandbox_id = sandbox_state.get("sandbox_id")
        if sandbox_id is not None:
            sandbox = get_sandbox_provider().get(sandbox_id)
            if sandbox is not None:
                runtime.context["sandbox_id"] = sandbox_id  # Ensure sandbox_id is in context for releasing in after_agent
                return sandbox
            # Sandbox was released, fall through to acquire new one

    # Lazy acquisition: get thread_id and acquire sandbox
    thread_id = get_thread_id(runtime)
    if thread_id is None:
        raise SandboxRuntimeError("Thread ID not available in runtime context")

    provider = get_sandbox_provider()
    sandbox_id = provider.acquire(thread_id)

    # Update runtime state - this persists across tool calls
    runtime.state["sandbox"] = {"sandbox_id": sandbox_id}

    # Retrieve and return the sandbox
    sandbox = provider.get(sandbox_id)
    if sandbox is None:
        raise SandboxNotFoundError("Sandbox not found after acquisition", sandbox_id=sandbox_id)

    runtime.context["sandbox_id"] = sandbox_id  # Ensure sandbox_id is in context for releasing in after_agent
    return sandbox


def ensure_thread_directories_exist(runtime: ToolRuntime[ContextT, ThreadState] | None) -> None:
    """Ensure thread data directories (workspace, uploads, outputs) exist.

    This function is called lazily when any sandbox tool is first used.
    For local sandbox, it creates the directories on the filesystem.
    For other sandboxes (like aio), directories are already mounted in the container.

    Args:
        runtime: Tool runtime containing state and context.
    """
    if runtime is None:
        return

    # Only create directories for local sandbox
    if not is_local_sandbox(runtime):
        return

    thread_data = get_thread_data(runtime)
    if thread_data is None:
        return

    # Check if directories have already been created
    if runtime.state.get("thread_directories_created"):
        return

    # Create the three directories
    import os

    for key in ["workspace_path", "uploads_path", "outputs_path"]:
        path = thread_data.get(key)
        if path:
            os.makedirs(path, exist_ok=True)

    # Mark as created to avoid redundant operations
    runtime.state["thread_directories_created"] = True


def _thread_id(runtime: ToolRuntime[ContextT, ThreadState] | None) -> str | None:
    if runtime is None:
        return None
    return runtime.context.get("thread_id")


def _outputs_dir(runtime: ToolRuntime[ContextT, ThreadState] | None) -> Path | None:
    thread_data = get_thread_data(runtime)
    if not thread_data:
        return None
    outputs_path = thread_data.get("outputs_path")
    if not outputs_path:
        return None
    return Path(outputs_path)


def _materialize_upload_path_if_needed(runtime: ToolRuntime[ContextT, ThreadState] | None, virtual_path: str) -> None:
    """Ensure upload file exists in local cache when command/tool needs a local path."""
    if runtime is None or not is_uploads_virtual_path(virtual_path):
        return
    thread_id = _thread_id(runtime)
    if not thread_id:
        return
    try:
        materialize_upload_to_local_cache(thread_id, virtual_path)
    except Exception:
        # Let downstream file operations surface the user-facing error details.
        return


def _materialize_uploads_in_command(runtime: ToolRuntime[ContextT, ThreadState] | None, command: str) -> None:
    """Materialize upload file arguments referenced directly in bash commands."""
    if runtime is None or VIRTUAL_PATH_PREFIX not in command:
        return
    matches = re.findall(rf"{re.escape(VIRTUAL_PATH_PREFIX)}/uploads/[^\s\"';&|<>()]+", command)
    for upload_path in sorted(set(matches)):
        _materialize_upload_path_if_needed(runtime, upload_path)


def _snapshot_outputs(runtime: ToolRuntime[ContextT, ThreadState] | None) -> dict[str, int]:
    outputs_dir = _outputs_dir(runtime)
    if outputs_dir is None or not outputs_dir.exists():
        return {}
    snapshot: dict[str, int] = {}
    for file_path in outputs_dir.rglob("*"):
        if not file_path.is_file():
            continue
        try:
            rel = file_path.relative_to(outputs_dir).as_posix()
            snapshot[rel] = file_path.stat().st_mtime_ns
        except OSError:
            continue
    return snapshot


def _publish_changed_outputs(runtime: ToolRuntime[ContextT, ThreadState] | None, before: dict[str, int]) -> None:
    thread_id = _thread_id(runtime)
    outputs_dir = _outputs_dir(runtime)
    if not thread_id or outputs_dir is None or not outputs_dir.exists():
        return

    after = _snapshot_outputs(runtime)
    for rel, mtime_ns in after.items():
        if before.get(rel) == mtime_ns:
            continue
        file_path = outputs_dir / rel
        virtual_path = f"{OUTPUTS_VIRTUAL_PREFIX}{rel}"
        publish_output_file(thread_id, virtual_path, file_path)


def _publish_single_output(runtime: ToolRuntime[ContextT, ThreadState] | None, original_path: str, resolved_path: str) -> None:
    thread_id = _thread_id(runtime)
    if not thread_id:
        return

    virtual_path = f"/{original_path.lstrip('/')}"
    if not virtual_path.startswith(OUTPUTS_VIRTUAL_PREFIX):
        return

    publish_output_file(thread_id, virtual_path, resolved_path)


@tool("bash", parse_docstring=True)
def bash_tool(runtime: ToolRuntime[ContextT, ThreadState], description: str, command: str) -> str:
    """Execute a bash command in a Linux environment.


    - Use `python` to run Python code.
    - Use `pip install` to install Python packages.

    Args:
        description: Explain why you are running this command in short words. ALWAYS PROVIDE THIS PARAMETER FIRST.
        command: The bash command to execute. Always use absolute paths for files and directories.
    """
    try:
        sandbox = ensure_sandbox_initialized(runtime)
        ensure_thread_directories_exist(runtime)
        _materialize_uploads_in_command(runtime, command)
        outputs_before = _snapshot_outputs(runtime)
        if is_local_sandbox(runtime):
            thread_data = get_thread_data(runtime)
            command = replace_virtual_paths_in_command(command, thread_data)
        result = sandbox.execute_command(command)
        _publish_changed_outputs(runtime, outputs_before)
        return result
    except SandboxError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error: Unexpected error executing command: {type(e).__name__}: {e}"


@tool("ls", parse_docstring=True)
def ls_tool(runtime: ToolRuntime[ContextT, ThreadState], description: str, path: str) -> str:
    """List the contents of a directory up to 2 levels deep in tree format.

    Args:
        description: Explain why you are listing this directory in short words. ALWAYS PROVIDE THIS PARAMETER FIRST.
        path: The **absolute** path to the directory to list.
    """
    try:
        sandbox = ensure_sandbox_initialized(runtime)
        ensure_thread_directories_exist(runtime)
        _materialize_upload_path_if_needed(runtime, path)
        if is_local_sandbox(runtime):
            thread_data = get_thread_data(runtime)
            path = replace_virtual_path(path, thread_data)
        children = sandbox.list_dir(path)
        if not children:
            return "(empty)"
        return "\n".join(children)
    except SandboxError as e:
        return f"Error: {e}"
    except FileNotFoundError:
        return f"Error: Directory not found: {path}"
    except PermissionError:
        return f"Error: Permission denied: {path}"
    except Exception as e:
        return f"Error: Unexpected error listing directory: {type(e).__name__}: {e}"


# File extensions that should be analyzed with code, not read into LLM context.
# These are data files where reading raw content is useless — the model needs
# pandas/python to aggregate, filter, and compute stats.
DATA_FILE_EXTENSIONS = {
    ".csv", ".tsv", ".json", ".jsonl", ".ndjson",
    ".xlsx", ".xls", ".parquet", ".feather", ".arrow",
    ".sqlite", ".db", ".sql",
}

# Binary/media files — cannot be read as text. Agent should use appropriate tools.
BINARY_FILE_EXTENSIONS = {
    # Images
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".svg", ".webp", ".ico", ".tiff",
    # Video
    ".mp4", ".mov", ".avi", ".mkv", ".webm", ".flv",
    # Audio
    ".mp3", ".wav", ".ogg", ".flac", ".aac", ".m4a",
    # Documents (binary)
    ".pdf", ".docx", ".pptx",
    # Archives
    ".zip", ".tar", ".gz", ".bz2", ".7z", ".rar",
    # Other binary
    ".exe", ".dll", ".so", ".dylib", ".wasm", ".pyc",
}

# For non-data files, truncate at this limit to prevent context blowup.
MAX_READ_FILE_CHARS = 8_000

# Number of preview lines to show for data files.
DATA_FILE_PREVIEW_LINES = 5


def _get_file_extension(path: str) -> str:
    """Extract lowercase file extension from path."""
    dot_idx = path.rfind(".")
    if dot_idx == -1:
        return ""
    return path[dot_idx:].lower()


def _build_data_file_preview(sandbox: Sandbox, content: str, path: str) -> str:
    """Build a schema-aware preview for data files.

    For CSV/TSV files, runs a quick python command in the sandbox to extract
    schema info (dtypes, null counts, shape) — just like ChatGPT Code Interpreter.
    Returns ~800 chars instead of the full file, saving thousands of tokens.
    """
    lines = content.splitlines()
    total_lines = len(lines)
    total_chars = len(content)
    ext = _get_file_extension(path)

    preview_lines = lines[:DATA_FILE_PREVIEW_LINES + 1]  # header + N data rows
    preview = "\n".join(preview_lines)

    # For CSV/TSV, run quick schema analysis in sandbox
    schema_info = ""
    if ext in (".csv", ".tsv"):
        try:
            schema_script = (
                "import pandas as pd\n"
                f"df = pd.read_csv('{path}'\n"
            )
            if ext == ".tsv":
                schema_script = (
                    "import pandas as pd\n"
                    f"df = pd.read_csv('{path}', sep='\\t'\n"
                )
            schema_script += (
                ", nrows=1000)\n"  # Read only first 1000 rows for speed
                "print(f'Shape: {df.shape[0]} rows x {df.shape[1]} columns')\n"
                "print()\n"
                "print('Column types:')\n"
                "for col in df.columns:\n"
                "    null_pct = df[col].isnull().mean() * 100\n"
                "    n_unique = df[col].nunique()\n"
                "    print(f'  {col}: {df[col].dtype} ({n_unique} unique, {null_pct:.0f}% null)')\n"
            )
            result = sandbox.execute_command(f"python3 -c \"{schema_script}\"")
            if result and "Error" not in result:
                schema_info = f"\n--- Schema (from first 1000 rows) ---\n{result}\n"
        except Exception:
            # Schema analysis failed — fall back to basic preview
            sep = "\t" if ext == ".tsv" else ","
            header = lines[0] if lines else ""
            cols = [c.strip().strip('"').strip("'") for c in header.split(sep)]
            schema_info = f"\nColumns ({len(cols)}): {', '.join(cols)}\n"

    return (
        f"[DATA FILE PREVIEW — not full content]\n"
        f"File: {path}\n"
        f"Size: {total_chars:,} chars, {total_lines:,} lines\n"
        f"{schema_info}"
        f"\n--- First {min(DATA_FILE_PREVIEW_LINES + 1, total_lines)} lines ---\n"
        f"{preview}\n"
        f"--- End preview ---\n\n"
        f"⚠ Do NOT re-read this file with read_file — use `bash` with python/pandas to analyze it.\n"
    )


def _build_binary_file_response(path: str) -> str:
    """Return guidance for binary files instead of trying to read them."""
    ext = _get_file_extension(path)

    if ext in (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tiff", ".svg"):
        return (
            f"[BINARY FILE — cannot read as text]\n"
            f"File: {path} (image)\n\n"
            f"To view this image, use the `view_image` tool.\n"
            f"To edit/process it, use `bash` with python:\n"
            f"  python3 -c \"from PIL import Image; img = Image.open('{path}'); print(img.size, img.mode)\"\n"
        )
    elif ext in (".mp4", ".mov", ".avi", ".mkv", ".webm", ".flv"):
        return (
            f"[BINARY FILE — cannot read as text]\n"
            f"File: {path} (video)\n\n"
            f"To get video info, use `bash`:\n"
            f"  python3 -c \"import subprocess; print(subprocess.run(['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_format', '-show_streams', '{path}'], capture_output=True, text=True).stdout)\"\n"
        )
    elif ext in (".mp3", ".wav", ".ogg", ".flac", ".aac", ".m4a"):
        return (
            f"[BINARY FILE — cannot read as text]\n"
            f"File: {path} (audio)\n\n"
            f"To get audio info, use `bash` with ffprobe or python.\n"
        )
    elif ext == ".pdf":
        # PDFs should have a .md conversion alongside
        md_path = path.rsplit(".", 1)[0] + ".md"
        return (
            f"[BINARY FILE — cannot read as text]\n"
            f"File: {path} (PDF)\n\n"
            f"A Markdown conversion should be available at: {md_path}\n"
            f"Try: read_file {md_path}\n"
        )
    else:
        return (
            f"[BINARY FILE — cannot read as text]\n"
            f"File: {path}\n\n"
            f"This is a binary file. Use `bash` with appropriate tools to inspect it.\n"
        )


@tool("read_file", parse_docstring=True)
def read_file_tool(
    runtime: ToolRuntime[ContextT, ThreadState],
    description: str,
    path: str,
    start_line: int | None = None,
    end_line: int | None = None,
) -> str:
    """Read the contents of a text file. Use this to examine source code, configuration files, or small text files.

    **Important**:
    - For data files (CSV, JSON, Parquet, etc.): Returns a schema preview + first rows. Use `bash` with python/pandas for analysis.
    - For images: Use `view_image` tool to see them, or `bash` with python/PIL to process them.
    - For video/audio: Use `bash` with ffprobe or python to get metadata.

    Args:
        description: Explain why you are reading this file in short words. ALWAYS PROVIDE THIS PARAMETER FIRST.
        path: The **absolute** path to the file to read.
        start_line: Optional starting line number (1-indexed, inclusive). Use with end_line to read a specific range.
        end_line: Optional ending line number (1-indexed, inclusive). Use with start_line to read a specific range.
    """
    try:
        sandbox = ensure_sandbox_initialized(runtime)
        ensure_thread_directories_exist(runtime)
        _materialize_upload_path_if_needed(runtime, path)
        if is_local_sandbox(runtime):
            thread_data = get_thread_data(runtime)
            path = replace_virtual_path(path, thread_data)

        # Binary files: return guidance instead of garbage
        ext = _get_file_extension(path)
        if ext in BINARY_FILE_EXTENSIONS:
            return _build_binary_file_response(path)

        content = sandbox.read_file(path)
        if not content:
            return "(empty)"

        # Data files: return schema preview (auto-analyzed in sandbox)
        if ext in DATA_FILE_EXTENSIONS and start_line is None:
            return _build_data_file_preview(sandbox, content, path)

        # Apply line range if specified
        if start_line is not None and end_line is not None:
            content = "\n".join(content.splitlines()[start_line - 1 : end_line])

        # Truncate large non-data files (code, logs, etc.)
        if len(content) > MAX_READ_FILE_CHARS:
            total_lines = len(content.splitlines())
            truncated = content[:MAX_READ_FILE_CHARS]
            return (
                f"{truncated}\n\n"
                f"... [TRUNCATED — {len(content):,} chars, {total_lines:,} lines. "
                f"Only first {MAX_READ_FILE_CHARS:,} chars shown.] ...\n"
                f"Use start_line/end_line to read specific sections, "
                f"or `bash` with grep/awk to search."
            )

        return content
    except SandboxError as e:
        return f"Error: {e}"
    except FileNotFoundError:
        return f"Error: File not found: {path}"
    except PermissionError:
        return f"Error: Permission denied reading file: {path}"
    except IsADirectoryError:
        return f"Error: Path is a directory, not a file: {path}"
    except Exception as e:
        return f"Error: Unexpected error reading file: {type(e).__name__}: {e}"


@tool("write_file", parse_docstring=True)
def write_file_tool(
    runtime: ToolRuntime[ContextT, ThreadState],
    description: str,
    path: str,
    content: str,
    append: bool = False,
) -> str:
    """Write text content to a file.

    Args:
        description: Explain why you are writing to this file in short words. ALWAYS PROVIDE THIS PARAMETER FIRST.
        path: The **absolute** path to the file to write to. ALWAYS PROVIDE THIS PARAMETER SECOND.
        content: The content to write to the file. ALWAYS PROVIDE THIS PARAMETER THIRD.
    """
    try:
        sandbox = ensure_sandbox_initialized(runtime)
        ensure_thread_directories_exist(runtime)
        original_path = path
        if is_local_sandbox(runtime):
            thread_data = get_thread_data(runtime)
            path = replace_virtual_path(path, thread_data)
        sandbox.write_file(path, content, append)
        _publish_single_output(runtime, original_path, path)
        return "OK"
    except SandboxError as e:
        return f"Error: {e}"
    except PermissionError:
        return f"Error: Permission denied writing to file: {path}"
    except IsADirectoryError:
        return f"Error: Path is a directory, not a file: {path}"
    except OSError as e:
        return f"Error: Failed to write file '{path}': {e}"
    except Exception as e:
        return f"Error: Unexpected error writing file: {type(e).__name__}: {e}"


@tool("str_replace", parse_docstring=True)
def str_replace_tool(
    runtime: ToolRuntime[ContextT, ThreadState],
    description: str,
    path: str,
    old_str: str,
    new_str: str,
    replace_all: bool = False,
) -> str:
    """Replace a substring in a file with another substring.
    If `replace_all` is False (default), the substring to replace must appear **exactly once** in the file.

    Args:
        description: Explain why you are replacing the substring in short words. ALWAYS PROVIDE THIS PARAMETER FIRST.
        path: The **absolute** path to the file to replace the substring in. ALWAYS PROVIDE THIS PARAMETER SECOND.
        old_str: The substring to replace. ALWAYS PROVIDE THIS PARAMETER THIRD.
        new_str: The new substring. ALWAYS PROVIDE THIS PARAMETER FOURTH.
        replace_all: Whether to replace all occurrences of the substring. If False, only the first occurrence will be replaced. Default is False.
    """
    try:
        sandbox = ensure_sandbox_initialized(runtime)
        ensure_thread_directories_exist(runtime)
        original_path = path
        if is_local_sandbox(runtime):
            thread_data = get_thread_data(runtime)
            path = replace_virtual_path(path, thread_data)
        content = sandbox.read_file(path)
        if not content:
            return "OK"
        if old_str not in content:
            return f"Error: String to replace not found in file: {path}"
        if replace_all:
            content = content.replace(old_str, new_str)
        else:
            content = content.replace(old_str, new_str, 1)
        sandbox.write_file(path, content)
        _publish_single_output(runtime, original_path, path)
        return "OK"
    except SandboxError as e:
        return f"Error: {e}"
    except FileNotFoundError:
        return f"Error: File not found: {path}"
    except PermissionError:
        return f"Error: Permission denied accessing file: {path}"
    except Exception as e:
        return f"Error: Unexpected error replacing string: {type(e).__name__}: {e}"
