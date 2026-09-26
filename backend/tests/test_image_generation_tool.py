"""The controlled image tool owns provider selection and shell failure boundaries."""

import json
import os
import re
import shutil
import subprocess
import sys
import threading
from base64 import b64encode
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.gateway.image_generation_probe import _solid_png
from deerflow.config.image_generation import ImageGenerationProfile, ManagedImageGenerationProfile
from deerflow.tools.builtins import image_generation_tool as image_tool


def config():
    return SimpleNamespace(
        sandbox=SimpleNamespace(environment={}, bash_command_timeout=600),
        skills=SimpleNamespace(container_path="/mnt/skills"),
    )


def test_model_facing_schema_hides_runtime_and_credentials():
    schema = image_tool.generate_image_tool.tool_call_schema.model_json_schema()
    assert set(schema["properties"]) == {"prompt_file", "output_file", "reference_images", "aspect_ratio"}
    assert "api_key" not in str(schema)


def test_image_key_is_redacted_even_when_short():
    assert "abc" not in image_tool._mask_image_secrets("provider echoed abc", {"IMAGE_GENERATION_API_KEY": "abc"})


def test_missing_profile_returns_before_sandbox_acquisition(monkeypatch):
    from deerflow.sandbox import tools as sandbox_tools

    monkeypatch.setattr(image_tool, "get_app_config", config)
    monkeypatch.setattr(image_tool, "resolve_image_generation_profile", lambda _env: (None, None, None))
    monkeypatch.setattr(sandbox_tools, "ensure_sandbox_initialized", lambda _runtime: pytest.fail("sandbox was acquired"))
    result = image_tool.generate_image_tool.func(SimpleNamespace(), "/mnt/user-data/workspace/prompt.json", "/mnt/user-data/outputs/slide.png")
    assert "IMAGE_PROVIDER_NOT_CONFIGURED" in result


@pytest.mark.asyncio
async def test_missing_profile_async_returns_before_sandbox_acquisition(monkeypatch):
    from deerflow.sandbox import tools as sandbox_tools

    monkeypatch.setattr(image_tool, "get_app_config", config)
    monkeypatch.setattr(image_tool, "resolve_image_generation_profile", lambda _env: (None, None, None))
    monkeypatch.setattr(sandbox_tools, "ensure_sandbox_initialized_async", lambda _runtime: pytest.fail("sandbox was acquired"))
    result = await image_tool.generate_image_tool.coroutine(SimpleNamespace(), "/mnt/user-data/workspace/prompt.json", "/mnt/user-data/outputs/slide.png")
    assert "IMAGE_PROVIDER_NOT_CONFIGURED" in result


def test_command_receives_secret_as_env_and_requires_success_marker(monkeypatch):
    from deerflow.sandbox import tools as sandbox_tools

    profile = ImageGenerationProfile(provider="openai", model="test-image", base_url="https://images.example/v1", api_key="synthetic-secret")
    monkeypatch.setattr(image_tool, "get_app_config", config)
    monkeypatch.setattr(image_tool, "resolve_image_generation_profile", lambda _env: (profile, "managed", None))
    monkeypatch.setattr(sandbox_tools, "ensure_sandbox_initialized", lambda _runtime: object())
    monkeypatch.setattr(sandbox_tools, "is_local_sandbox", lambda _runtime: False)
    captured = {}

    def execute(_sandbox, command, *, runtime, env, timeout):
        captured.update(command=command, env=env, timeout=timeout)
        assert "synthetic-secret" not in command
        return re.search(r"__DEERFLOW_IMAGE_OK_[a-f0-9]+__", command).group()

    monkeypatch.setattr(sandbox_tools, "_execute_bash_command", execute)
    result = image_tool.generate_image_tool.func(SimpleNamespace(context={}), "/mnt/user-data/workspace/prompt.json", "/mnt/user-data/outputs/slide.png")
    assert result.startswith("Successfully generated")
    assert captured["env"]["IMAGE_GENERATION_API_KEY"] == "synthetic-secret"
    assert "runpy.run_path" in captured["command"]
    assert "trap" not in captured["command"]

    monkeypatch.setattr(sandbox_tools, "_execute_bash_command", lambda *_args, **_kwargs: "Exit Code: 1")
    failure = image_tool.generate_image_tool.func(SimpleNamespace(context={}), "/mnt/user-data/workspace/prompt.json", "/mnt/user-data/outputs/slide.png")
    assert "IMAGE_GENERATION_FAILED" in failure
    assert "Exit Code: 1" in failure


def test_local_image_command_does_not_require_a_posix_shell(monkeypatch):
    from deerflow.sandbox import tools as sandbox_tools

    profile = ImageGenerationProfile(provider="openai", model="test-image", base_url="https://images.example/v1", api_key="synthetic-secret")
    settings = config()
    settings.skills.get_skills_path = lambda: Path("/Program Files/Deer Flow/skills")
    monkeypatch.setattr(image_tool, "get_app_config", lambda: settings)
    monkeypatch.setattr(image_tool, "resolve_image_generation_profile", lambda _env: (profile, "managed", None))
    monkeypatch.setattr(image_tool, "is_host_bash_allowed", lambda: True)
    monkeypatch.setattr(sandbox_tools, "ensure_sandbox_initialized", lambda _runtime: object())
    monkeypatch.setattr(sandbox_tools, "is_local_sandbox", lambda _runtime: True)
    monkeypatch.setattr(sandbox_tools, "get_thread_data", lambda _runtime: {})
    monkeypatch.setattr(sandbox_tools, "_resolve_and_validate_user_data_path", lambda path, _data: f"C:\\User Files\\O'Brien & Co\\{path.rsplit('/', 1)[-1]}")
    monkeypatch.setattr(sandbox_tools, "mask_local_paths_in_output", lambda output, _data: output)
    captured = {}

    def execute(_sandbox, command, *, runtime, env, timeout):
        captured["command"] = command
        return "Exit Code: 1"

    monkeypatch.setattr(sandbox_tools, "_execute_bash_command", execute)
    result = image_tool.generate_image_tool.func(
        SimpleNamespace(context={}),
        "/mnt/user-data/workspace/prompt.json",
        "/mnt/user-data/outputs/slide.png",
    )

    assert "IMAGE_GENERATION_FAILED" in result
    command = captured["command"]
    assert command.startswith('python -c "')
    assert "trap " not in command
    assert " && " not in command
    assert " mv " not in command
    assert " rm " not in command
    assert "printf " not in command
    assert "O'Brien & Co" not in command


def test_local_sandbox_powershell_fallback_receives_image_launcher(monkeypatch):
    from deerflow.sandbox.local import local_sandbox as local_module
    from deerflow.sandbox.local.local_sandbox import LocalSandbox

    command = image_tool._python_script_command(
        [r"C:\Program Files\Deer Flow\generate.py", r"C:\User Files\O'Brien & Co\幻灯片.png"],
        "__DEERFLOW_IMAGE_OK_test__",
    )
    observed = {}

    def fake_run(args, timeout, env, *, encoding=None):
        observed.update(args=args, env=env, encoding=encoding)
        return "__DEERFLOW_IMAGE_OK_test__\n", "", 0, False

    monkeypatch.setattr(local_module.os, "name", "nt")
    monkeypatch.setattr(local_module.os, "environ", {"PATH": r"C:\Windows"})
    monkeypatch.setattr(LocalSandbox, "_get_shell", staticmethod(lambda: "powershell.exe"))
    monkeypatch.setattr(LocalSandbox, "_run_windows_command", staticmethod(fake_run))

    result = LocalSandbox("image-probe").execute_command(command, env={"IMAGE_GENERATION_API_KEY": "synthetic-secret"})

    assert result.strip() == "__DEERFLOW_IMAGE_OK_test__"
    assert observed["args"][:3] == ["powershell.exe", "-NoProfile", "-Command"]
    assert observed["args"][3].endswith(command)
    assert observed["env"]["IMAGE_GENERATION_API_KEY"] == "synthetic-secret"
    assert observed["encoding"] == "utf-8"


@pytest.mark.skipif(os.name != "nt", reason="requires a Windows shell fallback")
@pytest.mark.parametrize(("shell_name", "flag"), [("powershell.exe", "-Command"), ("cmd.exe", "/c")])
def test_python_image_launcher_runs_in_windows_shell(tmp_path, shell_name, flag):
    shell = shutil.which(shell_name)
    if shell is None:
        pytest.skip(f"{shell_name} is unavailable")
    script = tmp_path / "script with spaces.py"
    script.write_text("import json,sys;print(json.dumps(sys.argv[1:]))", encoding="utf-8")
    argument = "C:\\User Files\\O'Brien & Co\\幻灯片.png"
    marker = "__DEERFLOW_IMAGE_OK_test__"
    command = image_tool._python_script_command([str(script), argument], marker)

    invocation = [shell, "-NoProfile", flag, command] if shell_name == "powershell.exe" else [shell, flag, command]
    result = subprocess.run(
        invocation,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert [argument, "--success-marker", marker] == json.loads(result.stdout.strip())

    script.write_text("raise SystemExit(7)", encoding="utf-8")
    failed = subprocess.run(invocation, capture_output=True, text=True, check=False)
    assert failed.returncode != 0
    assert marker not in failed.stdout


def test_legacy_aio_profile_uses_container_environment_without_bash_exec(monkeypatch):
    from deerflow.community.aio_sandbox.aio_sandbox import AioSandbox
    from deerflow.sandbox import tools as sandbox_tools

    profile = ImageGenerationProfile(provider="openai", model="test-image", base_url="https://images.example/v1", api_key="synthetic-secret")
    monkeypatch.setattr(image_tool, "get_app_config", config)
    monkeypatch.setattr(image_tool, "resolve_image_generation_profile", lambda _env: (profile, "sandbox_environment", None))
    monkeypatch.setattr(sandbox_tools, "ensure_sandbox_initialized", lambda _runtime: object.__new__(AioSandbox))
    monkeypatch.setattr(sandbox_tools, "is_local_sandbox", lambda _runtime: False)
    captured = {}

    def execute(_sandbox, command, *, runtime, env, timeout):
        captured["env"] = env
        return re.search(r"__DEERFLOW_IMAGE_OK_[a-f0-9]+__", command).group()

    monkeypatch.setattr(sandbox_tools, "_execute_bash_command", execute)
    result = image_tool.generate_image_tool.func(SimpleNamespace(context={}), "/mnt/user-data/workspace/prompt.json", "/mnt/user-data/outputs/slide.png")

    assert result.startswith("Successfully generated")
    assert captured["env"] is None

    monkeypatch.setattr(sandbox_tools, "_execute_bash_command", lambda *_args, **_kwargs: "synthetic-secret\nExit Code: 1")
    failure = image_tool.generate_image_tool.func(SimpleNamespace(context={}), "/mnt/user-data/workspace/prompt.json", "/mnt/user-data/outputs/slide.png")
    assert "IMAGE_GENERATION_FAILED" in failure
    assert "synthetic-secret" not in failure


@pytest.mark.parametrize("supports_env", [True, False])
def test_web_image_profile_selects_container_command_mode_only_for_matching_revision(monkeypatch, supports_env):
    from deerflow.community.aio_sandbox.aio_sandbox import AioSandbox
    from deerflow.sandbox import tools as sandbox_tools

    profile = ManagedImageGenerationProfile(name="image", provider="openai", model="test-image", base_url="https://images.example/v1", api_key="synthetic-secret", revision="revision-1")
    sandbox = object.__new__(AioSandbox)
    sandbox._deerflow_managed_image_local = True
    sandbox._deerflow_image_profile_revision = "revision-1"
    monkeypatch.setattr(sandbox, "supports_command_environment", lambda: supports_env)
    monkeypatch.setattr(image_tool, "get_app_config", config)
    monkeypatch.setattr(image_tool, "resolve_image_generation_profile", lambda _env: (profile, "managed", profile))
    monkeypatch.setattr(sandbox_tools, "ensure_sandbox_initialized", lambda _runtime: sandbox)
    monkeypatch.setattr(sandbox_tools, "is_local_sandbox", lambda _runtime: False)
    received = []

    def execute(_sandbox, command, *, runtime, env, timeout):
        received.append(env)
        return re.search(r"__DEERFLOW_IMAGE_OK_[a-f0-9]+__", command).group()

    monkeypatch.setattr(sandbox_tools, "_execute_bash_command", execute)
    args = (SimpleNamespace(context={}), "/mnt/user-data/workspace/prompt.json", "/mnt/user-data/outputs/slide.png")
    assert image_tool.generate_image_tool.func(*args).startswith("Successfully generated")
    assert received == [profile.command_environment() if supports_env else None]

    sandbox._deerflow_image_profile_revision = "previous-revision"
    assert "IMAGE_PROFILE_CHANGED" in image_tool.generate_image_tool.func(*args)
    assert received == [profile.command_environment() if supports_env else None]


def test_rejects_path_traversal_before_sandbox(monkeypatch):
    from deerflow.sandbox import tools as sandbox_tools

    profile = ImageGenerationProfile(provider="openai", model="test-image", base_url="https://images.example/v1", api_key="synthetic-secret")
    monkeypatch.setattr(image_tool, "get_app_config", config)
    monkeypatch.setattr(image_tool, "resolve_image_generation_profile", lambda _env: (profile, "managed", None))
    monkeypatch.setattr(sandbox_tools, "ensure_sandbox_initialized", lambda _runtime: pytest.fail("sandbox was acquired"))
    result = image_tool.generate_image_tool.func(SimpleNamespace(state={}, context={}), "/mnt/user-data/workspace/../outside.json", "/mnt/user-data/outputs/slide.png")
    assert "IMAGE_GENERATION_INVALID_REQUEST" in result


def test_local_sandbox_error_masks_host_paths(monkeypatch):
    from deerflow.sandbox import tools as sandbox_tools

    profile = ImageGenerationProfile(provider="openai", model="test-image", base_url="https://images.example/v1", api_key="synthetic-secret")
    settings = config()
    settings.skills.get_skills_path = lambda: Path("/host/skills")
    monkeypatch.setattr(image_tool, "get_app_config", lambda: settings)
    monkeypatch.setattr(image_tool, "resolve_image_generation_profile", lambda _env: (profile, "managed", None))
    monkeypatch.setattr(image_tool, "is_host_bash_allowed", lambda: True)
    monkeypatch.setattr(sandbox_tools, "ensure_sandbox_initialized", lambda _runtime: object())
    monkeypatch.setattr(sandbox_tools, "is_local_sandbox", lambda _runtime: True)
    monkeypatch.setattr(sandbox_tools, "get_thread_data", lambda _runtime: {})
    monkeypatch.setattr(sandbox_tools, "_resolve_and_validate_user_data_path", lambda path, _data: f"/host{path}")
    monkeypatch.setattr(sandbox_tools, "_execute_bash_command", lambda *_args, **_kwargs: "Error: /host/mnt/user-data/workspace/prompt.json\nExit Code: 1")
    monkeypatch.setattr(sandbox_tools, "mask_local_paths_in_output", lambda output, _data: output.replace("/host/mnt/user-data", "/mnt/user-data"))
    result = image_tool.generate_image_tool.func(SimpleNamespace(context={}), "/mnt/user-data/workspace/prompt.json", "/mnt/user-data/outputs/slide.png")
    assert "IMAGE_GENERATION_FAILED" in result
    assert "/host/mnt/user-data" not in result


def test_image_tool_runs_script_and_validates_output_against_local_fake_provider(monkeypatch, tmp_path):
    from PIL import Image

    from deerflow.sandbox import tools as sandbox_tools

    class Handler(BaseHTTPRequestHandler):
        fail = False

        def do_POST(self):
            assert self.path == "/v1/images/generations"
            length = int(self.headers["Content-Length"])
            assert b"fake-image" in self.rfile.read(length)
            if self.fail:
                self.send_response(429)
                self.end_headers()
                return
            body = ('{"data":[{"b64_json":"' + b64encode(_solid_png()).decode() + '"}]}').encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        root = Path(__file__).resolve().parents[2]
        tmp_path = tmp_path / "O'Brien & Co"
        (tmp_path / "workspace").mkdir(parents=True)
        (tmp_path / "outputs").mkdir()
        (tmp_path / "workspace" / "prompt.txt").write_text("a blue square", encoding="utf-8")
        profile = ImageGenerationProfile(
            provider="openai",
            model="fake-image",
            base_url=f"http://127.0.0.1:{server.server_port}/v1",
            api_key="synthetic-secret",
        )
        monkeypatch.setattr(
            image_tool,
            "get_app_config",
            lambda: SimpleNamespace(
                sandbox=SimpleNamespace(environment={}, bash_command_timeout=20),
                skills=SimpleNamespace(container_path=str(root / "skills"), get_skills_path=lambda: root / "skills"),
            ),
        )
        monkeypatch.setattr(image_tool, "resolve_image_generation_profile", lambda _env: (profile, "managed", None))
        monkeypatch.setattr(sandbox_tools, "ensure_sandbox_initialized", lambda _runtime: object())
        monkeypatch.setattr(sandbox_tools, "is_local_sandbox", lambda _runtime: True)
        monkeypatch.setattr(image_tool, "is_host_bash_allowed", lambda: True)
        monkeypatch.setattr(sandbox_tools, "get_thread_data", lambda _runtime: {})
        monkeypatch.setattr(sandbox_tools, "_resolve_and_validate_user_data_path", lambda path, _data: str(tmp_path / path.removeprefix("/mnt/user-data/")))
        monkeypatch.setattr(sandbox_tools, "mask_local_paths_in_output", lambda output, _data: output)

        def execute(_sandbox, command, *, runtime, env, timeout):
            process = subprocess.run(
                command,
                shell=True,
                executable="/bin/sh",
                env={**os.environ, **env, "PATH": f"{Path(sys.executable).parent}:{os.environ.get('PATH', '')}"},
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            output = process.stdout + process.stderr
            return output if process.returncode == 0 else f"{output}\nExit Code: {process.returncode}"

        monkeypatch.setattr(sandbox_tools, "_execute_bash_command", execute)
        result = image_tool.generate_image_tool.func(
            SimpleNamespace(context={}),
            "/mnt/user-data/workspace/prompt.txt",
            "/mnt/user-data/outputs/slide.png",
        )
        assert result.startswith("Successfully generated")
        with Image.open(tmp_path / "outputs" / "slide.png") as image:
            image.verify()
        jpeg_result = image_tool.generate_image_tool.func(
            SimpleNamespace(context={}),
            "/mnt/user-data/workspace/prompt.txt",
            "/mnt/user-data/outputs/slide.jpg",
        )
        assert jpeg_result.startswith("Successfully generated")
        with Image.open(tmp_path / "outputs" / "slide.jpg") as image:
            assert image.format == "JPEG"
        expected_outputs = {tmp_path / "outputs" / "slide.png", tmp_path / "outputs" / "slide.jpg"}
        assert set((tmp_path / "outputs").iterdir()) == expected_outputs
        Handler.fail = True
        previous = (tmp_path / "outputs" / "slide.png").read_bytes()
        failure = image_tool.generate_image_tool.func(
            SimpleNamespace(context={}),
            "/mnt/user-data/workspace/prompt.txt",
            "/mnt/user-data/outputs/slide.png",
        )
        assert "IMAGE_GENERATION_FAILED" in failure
        assert "IMAGE_PROVIDER_RATE_LIMITED" in failure
        assert "429" in failure
        assert (tmp_path / "outputs" / "slide.png").read_bytes() == previous
        assert set((tmp_path / "outputs").iterdir()) == expected_outputs
    finally:
        server.shutdown()
        worker.join(timeout=3)
        server.server_close()
