"""Controlled image-generation entry point for managed provider credentials."""

import base64
import json
import posixpath
import uuid

from langchain.tools import tool

from deerflow.config.app_config import get_app_config
from deerflow.config.image_generation import ImageConfigurationError, resolve_image_generation_profile
from deerflow.config.paths import VIRTUAL_PATH_PREFIX
from deerflow.sandbox.security import is_host_bash_allowed
from deerflow.tools.types import Runtime

_IMAGE_SCRIPT = "public/image-generation/scripts/generate.py"
_OUTPUTS = f"{VIRTUAL_PATH_PREFIX}/outputs/"


def _mask_image_secrets(output: str, env: dict[str, str]) -> str:
    from deerflow.sandbox.tools import mask_secret_values

    safe = mask_secret_values(output, env)
    # The generic masker skips very short values to avoid corrupting ordinary
    # shell output. A selected API key must be redacted even when short.
    for name in ("GEMINI_API_KEY", "MINIMAX_API_KEY", "IMAGE_GENERATION_API_KEY"):
        key = env.get(name)
        if key:
            safe = safe.replace(key, "[redacted]")
    return safe


def _image_path(path: str, *, output: bool = False) -> str:
    """Keep script file arguments inside the current thread's virtual data tree."""
    if not isinstance(path, str) or "\x00" in path or not path.startswith(f"{VIRTUAL_PATH_PREFIX}/"):
        raise ValueError("Image paths must be absolute paths under /mnt/user-data/")
    normalized = posixpath.normpath(path)
    if normalized != path or ".." in path.split("/"):
        raise ValueError("Image paths cannot contain traversal or redundant segments")
    if output and (not path.startswith(_OUTPUTS) or not path.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))):
        raise ValueError("Image output must be a PNG, JPEG or WebP file under /mnt/user-data/outputs/")
    return path


def _python_script_command(args: list[str], marker: str) -> str:
    """Pass paths as data through POSIX, PowerShell and cmd.exe shells."""
    payload = base64.urlsafe_b64encode(json.dumps(args, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).decode("ascii")
    program = ";".join(
        (
            "import base64,json,runpy,sys",
            "marker=sys.argv[1]",
            f"sys.argv=json.loads(base64.urlsafe_b64decode('{payload}'))+['--success-marker',marker]",
            "runpy.run_path(sys.argv[0],run_name='__main__')",
        )
    )
    return f'python -c "{program}" {marker}'


@tool("check_image_generation", parse_docstring=True)
def check_image_generation_tool() -> str:
    """Check whether an image provider is configured before planning image or PPT work."""
    try:
        profile, source, managed = resolve_image_generation_profile(get_app_config().sandbox.environment)
        if profile is None:
            return "Error: IMAGE_PROVIDER_NOT_CONFIGURED. Configure an image model in Settings > Models > Image models."
        if not profile.usable():
            return "Error: IMAGE_PROVIDER_INVALID_CONFIG. The selected image model has no API key. Open Settings > Models > Image models."
        verified = bool(managed and managed.verified_generation and managed.verified_edit)
        status = "verified for generation and editing" if verified else "configured; image generation and editing have not both been verified"
        return f"Image provider {profile.provider.value}/{profile.model} from {source}: {status}."
    except (ImageConfigurationError, ValueError, OSError):
        return "Error: IMAGE_PROVIDER_INVALID_CONFIG. Check Settings > Models > Image models."


@tool("generate_image", parse_docstring=True)
def generate_image_tool(
    runtime: Runtime,
    prompt_file: str,
    output_file: str,
    reference_images: list[str] | None = None,
    aspect_ratio: str = "16:9",
) -> str:
    """Generate one image from a prompt file, optionally using reference images.

    Use this tool for the built-in image-generation and ppt-generation skills.
    It selects the configured image provider and checks the resulting file.

    Args:
        prompt_file: Absolute prompt path under /mnt/user-data/.
        output_file: Absolute image path under /mnt/user-data/outputs/.
        reference_images: Earlier image paths under /mnt/user-data/.
        aspect_ratio: Requested image aspect ratio, such as 16:9 or 1:1.
    """
    from deerflow.sandbox.tools import (
        _execute_bash_command,
        _resolve_and_validate_user_data_path,
        _sanitize_error,
        _truncate_bash_output,
        ensure_sandbox_initialized,
        get_thread_data,
        is_local_sandbox,
        mask_local_paths_in_output,
    )

    env: dict[str, str] = {}
    try:
        # Resolve before acquiring a sandbox or touching a provider API.
        profile, source, managed = resolve_image_generation_profile(get_app_config().sandbox.environment)
        if profile is None:
            return "Error: IMAGE_PROVIDER_NOT_CONFIGURED. Configure an image model in Settings > Models > Image models."
        env = profile.command_environment()
    except (ImageConfigurationError, ValueError, OSError):
        return "Error: IMAGE_PROVIDER_INVALID_CONFIG. Check Settings > Models > Image models."

    try:
        prompt = _image_path(prompt_file)
        output = _image_path(output_file, output=True)
        references = [_image_path(path) for path in (reference_images or [])]
        if aspect_ratio not in {"1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3"}:
            raise ValueError("Unsupported image aspect ratio")

        sandbox = ensure_sandbox_initialized(runtime)
        command_env = env
        from deerflow.community.aio_sandbox.aio_sandbox import AioSandbox

        if source == "sandbox_environment":
            if isinstance(sandbox, AioSandbox):
                if getattr(sandbox, "_deerflow_managed_image_local", False):
                    # A held local container may have been created for a web
                    # profile before it was disabled. Its derived ID survives
                    # rebinding even if the current revision marker does not.
                    base_id = getattr(sandbox, "_deerflow_base_identity", None)
                    if not base_id or sandbox.id != base_id:
                        return "Error: IMAGE_PROFILE_CHANGED. The image model changed during this run; retry after the active sandbox is replaced."
                # Legacy AIO containers receive sandbox.environment at creation.
                # Reuse that environment through the old shell API so an image
                # profile from config.yaml does not require /v1/bash/exec.
                command_env = None
        elif source == "managed" and isinstance(sandbox, AioSandbox) and getattr(sandbox, "_deerflow_managed_image_local", False):
            if managed is None or getattr(sandbox, "_deerflow_image_profile_revision", None) != managed.revision:
                return "Error: IMAGE_PROFILE_CHANGED. The image model changed during this run; retry in a new turn."
            if not sandbox.supports_command_environment():
                # This container was recreated with this exact profile at startup.
                # Old AIO images execute through their persistent shell endpoint.
                command_env = None
        thread_data = None
        if is_local_sandbox(runtime):
            if not is_host_bash_allowed():
                return "Error: Host bash is disabled by sandbox policy"
            thread_data = get_thread_data(runtime)
            prompt = _resolve_and_validate_user_data_path(prompt, thread_data)
            output = _resolve_and_validate_user_data_path(output, thread_data)
            references = [_resolve_and_validate_user_data_path(path, thread_data) for path in references]
            script = str(get_app_config().skills.get_skills_path() / _IMAGE_SCRIPT)
        else:
            script = f"{get_app_config().skills.container_path.rstrip('/')}/{_IMAGE_SCRIPT}"

        args = [script, "--prompt-file", prompt, "--output-file", output, "--aspect-ratio", aspect_ratio]
        if references:
            args.extend(["--reference-images", *references])
        marker = f"__DEERFLOW_IMAGE_OK_{uuid.uuid4().hex}__"
        # Only ASCII base64 and the server-generated marker cross the shell
        # boundary. PowerShell 5.1, cmd.exe and POSIX shells can all pass this
        # single Python invocation without interpreting user-controlled paths.
        command = _python_script_command(args, marker)
        raw = _execute_bash_command(
            sandbox,
            command,
            runtime=runtime,
            env=command_env,
            timeout=get_app_config().sandbox.bash_command_timeout,
        )
        if thread_data is not None:
            raw = mask_local_paths_in_output(raw, thread_data)
        safe = _mask_image_secrets(raw, env)
        if not safe.strip().splitlines() or safe.strip().splitlines()[-1] != marker:
            return _truncate_bash_output(f"Error: IMAGE_GENERATION_FAILED. {safe}", 20000)
        return f"Successfully generated and validated image: {output_file}"
    except (ValueError, PermissionError) as exc:
        return f"Error: IMAGE_GENERATION_INVALID_REQUEST. {_mask_image_secrets(_sanitize_error(exc, runtime), env)}"
    except Exception as exc:
        return f"Error: IMAGE_GENERATION_FAILED. {_mask_image_secrets(_sanitize_error(exc, runtime), env)}"


async def _generate_image_async(runtime: Runtime, prompt_file: str, output_file: str, reference_images: list[str] | None = None, aspect_ratio: str = "16:9") -> str:
    from deerflow.sandbox.tools import _run_sync_tool_after_async_sandbox_init

    # Return before the helper acquires a sandbox when configuration is absent.
    try:
        profile, _, _ = resolve_image_generation_profile(get_app_config().sandbox.environment)
        if profile is None:
            return "Error: IMAGE_PROVIDER_NOT_CONFIGURED. Configure an image model in Settings > Models > Image models."
        if not profile.usable():
            return "Error: IMAGE_PROVIDER_INVALID_CONFIG. The selected image model has no API key."
    except (ImageConfigurationError, ValueError, OSError):
        return "Error: IMAGE_PROVIDER_INVALID_CONFIG. Check Settings > Models > Image models."

    # The shared helper uses the provider's async acquire path and runs the
    # synchronous command on a worker thread after authorization.
    return await _run_sync_tool_after_async_sandbox_init(generate_image_tool.func, runtime, prompt_file, output_file, reference_images, aspect_ratio)


generate_image_tool.coroutine = _generate_image_async
