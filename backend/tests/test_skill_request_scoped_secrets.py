"""Tests for request-scoped secret injection into skills (issue #3861).

Covers the full feature surface:
  - Slice 1: ``Sandbox.execute_command(command, env=...)`` per-call env injection
    on both the local and AIO backends.
  - Slice 2: ``SKILL.md`` ``requires-secrets`` frontmatter parsing.
  - Slice 3: gateway carrier (``context.secrets``) and runtime-context passthrough.
  - Slice 4: activation-turn binding + ``bash`` tool injection.
  - Slice 5: the five leak surfaces (prompt / trace / checkpoint / audit / stdout).
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from deerflow.sandbox.local.local_sandbox import LocalSandbox


class TestLocalSandboxEnvInjection:
    """LocalSandbox.execute_command(env=...) injects per-call env into the subprocess."""

    def test_injected_env_visible_to_command(self):
        sandbox = LocalSandbox(id="local")
        out = sandbox.execute_command(
            "echo $DEERFLOW_TEST_SECRET",
            env={"DEERFLOW_TEST_SECRET": "s3cret-value"},
        )
        assert "s3cret-value" in out

    def test_env_none_keeps_inherited_environment(self, monkeypatch):
        """env=None preserves the legacy inherited-os.environ behaviour."""
        monkeypatch.setenv("DEERFLOW_INHERITED_VAR", "inherited-value")
        sandbox = LocalSandbox(id="local")
        out = sandbox.execute_command("echo $DEERFLOW_INHERITED_VAR")
        assert "inherited-value" in out

    def test_injected_env_is_per_call_only(self):
        """Injected env must not leak into a subsequent call that does not pass it."""
        sandbox = LocalSandbox(id="local")
        sandbox.execute_command("true", env={"DEERFLOW_EPHEMERAL": "leaky"})
        out = sandbox.execute_command("echo [$DEERFLOW_EPHEMERAL]")
        assert "leaky" not in out

    def test_platform_secret_scrubbed_from_inherited_env(self, monkeypatch):
        """A platform credential present in os.environ must NOT reach the sandbox
        subprocess (the baseline-env leak surface). Without this, scoped injection
        is security theatre — a skill script could simply read $OPENAI_API_KEY."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-platform-should-not-leak")
        sandbox = LocalSandbox(id="local")
        out = sandbox.execute_command("echo [$OPENAI_API_KEY]")
        assert "sk-platform-should-not-leak" not in out

    def test_benign_env_still_inherited_after_scrub(self, monkeypatch):
        """Scrubbing platform secrets must not strip harmless vars that skills rely on."""
        monkeypatch.setenv("DEERFLOW_PLAIN_VAR", "harmless-value")
        sandbox = LocalSandbox(id="local")
        out = sandbox.execute_command("echo [$DEERFLOW_PLAIN_VAR]")
        assert "harmless-value" in out

    def test_injected_secret_survives_scrub(self, monkeypatch):
        """An explicitly injected secret must win even if its name matches a blocked
        pattern — injection happens after scrubbing the inherited environment."""
        sandbox = LocalSandbox(id="local")
        out = sandbox.execute_command(
            "echo [$INJECTED_API_KEY]",
            env={"INJECTED_API_KEY": "scoped-value"},
        )
        assert "scoped-value" in out


class TestAioSandboxEnvInjection:
    @pytest.fixture
    def sandbox(self):
        with patch("deerflow.community.aio_sandbox.aio_sandbox.AioSandboxClient"):
            from deerflow.community.aio_sandbox.aio_sandbox import AioSandbox

            return AioSandbox(id="test-sandbox", base_url="http://localhost:8080")

    def test_env_none_uses_legacy_shell_path(self, sandbox):
        """No injected env → unchanged shell.exec_command path (backward compat)."""
        sandbox._client.shell.exec_command = MagicMock(return_value=SimpleNamespace(data=SimpleNamespace(output="hello")))
        sandbox._client.bash.exec = MagicMock()
        out = sandbox.execute_command("echo hello")
        sandbox._client.shell.exec_command.assert_called_once()
        sandbox._client.bash.exec.assert_not_called()
        assert "hello" in out

    def test_injected_env_uses_bash_exec_with_env_dict(self, sandbox):
        """Injected env → bash.exec(env=...) carries the dict; secret stays out of the command string."""
        sandbox._client.bash.exec = MagicMock(return_value=SimpleNamespace(data=SimpleNamespace(stdout="hello", stderr=None)))
        sandbox._client.shell.exec_command = MagicMock()
        out = sandbox.execute_command("echo $TOK", env={"TOK": "secret-v"})
        sandbox._client.bash.exec.assert_called_once()
        _, kwargs = sandbox._client.bash.exec.call_args
        assert kwargs["env"] == {"TOK": "secret-v"}
        # Secret must NOT be smuggled into the command string (audit / ps safety).
        assert "secret-v" not in kwargs["command"]
        sandbox._client.shell.exec_command.assert_not_called()
        assert "hello" in out


class TestEnvPolicy:
    """Platform-secret scrubbing policy for sandbox subprocesses (delta 1)."""

    @pytest.mark.parametrize(
        "name",
        [
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "LANGFUSE_SECRET_KEY",
            "GITHUB_TOKEN",
            "AWS_SECRET_ACCESS_KEY",
            "DB_PASSWORD",
            "MY_SERVICE_CREDENTIAL",
            "api_key",
            "Some_Token_Here",
        ],
    )
    def test_secret_like_names_are_blocked(self, name):
        from deerflow.sandbox.env_policy import is_blocked_env_name

        assert is_blocked_env_name(name) is True

    @pytest.mark.parametrize(
        "name",
        [
            "PATH",
            "HOME",
            "SHELL",
            "USER",
            "LANG",
            "LC_ALL",
            "PWD",
            "TMPDIR",
            "VIRTUAL_ENV",
            "PYTHONPATH",
            "DEERFLOW_PLAIN_VAR",
        ],
    )
    def test_benign_names_are_allowed(self, name):
        from deerflow.sandbox.env_policy import is_blocked_env_name

        assert is_blocked_env_name(name) is False

    def test_build_sandbox_env_scrubs_inherited_and_layers_injected(self, monkeypatch):
        from deerflow.sandbox.env_policy import build_sandbox_env

        monkeypatch.setenv("OPENAI_API_KEY", "platform-key-should-vanish")
        monkeypatch.setenv("HARMLESS_PLAIN", "ok")
        env = build_sandbox_env(injected={"SCOPED_TOKEN": "v"})
        assert "OPENAI_API_KEY" not in env  # platform secret scrubbed
        assert env.get("HARMLESS_PLAIN") == "ok"  # benign preserved
        assert env.get("SCOPED_TOKEN") == "v"  # injected layered on top
        assert env.get("PATH")  # core var preserved

    def test_build_sandbox_env_none_injection_still_scrubs(self, monkeypatch):
        from deerflow.sandbox.env_policy import build_sandbox_env

        monkeypatch.setenv("ANTHROPIC_API_KEY", "leak")
        env = build_sandbox_env()
        assert "ANTHROPIC_API_KEY" not in env


class TestRequiredSecretsParsing:
    """SKILL.md ``required-secrets`` frontmatter parsing (Slice 2)."""

    def _write_skill(self, tmp_path, frontmatter_body: str):
        skill_dir = tmp_path / "erp-report"
        skill_dir.mkdir()
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text(f"---\n{frontmatter_body}\n---\n# body\n", encoding="utf-8")
        return skill_file

    def test_absent_field_defaults_to_empty(self, tmp_path):
        from deerflow.skills.parser import parse_skill_file
        from deerflow.skills.types import SkillCategory

        skill_file = self._write_skill(tmp_path, "name: erp-report\ndescription: Pull an ERP report")
        skill = parse_skill_file(skill_file, SkillCategory.CUSTOM)
        assert skill is not None
        assert skill.required_secrets == []

    def test_string_list_form(self, tmp_path):
        from deerflow.skills.parser import parse_skill_file
        from deerflow.skills.types import SkillCategory

        skill_file = self._write_skill(
            tmp_path,
            "name: erp-report\ndescription: d\nrequired-secrets:\n  - ERP_TOKEN\n  - OTHER_TOKEN",
        )
        skill = parse_skill_file(skill_file, SkillCategory.CUSTOM)
        assert [s.name for s in skill.required_secrets] == ["ERP_TOKEN", "OTHER_TOKEN"]
        assert all(s.optional is False for s in skill.required_secrets)

    def test_object_list_with_optional(self, tmp_path):
        from deerflow.skills.parser import parse_skill_file
        from deerflow.skills.types import SkillCategory

        skill_file = self._write_skill(
            tmp_path,
            "name: erp-report\ndescription: d\nrequired-secrets:\n  - name: ERP_TOKEN\n    optional: true\n  - name: REQUIRED_ONE",
        )
        skill = parse_skill_file(skill_file, SkillCategory.CUSTOM)
        by_name = {s.name: s for s in skill.required_secrets}
        assert by_name["ERP_TOKEN"].optional is True
        assert by_name["REQUIRED_ONE"].optional is False

    def test_invalid_env_name_entry_is_dropped(self, tmp_path):
        from deerflow.skills.parser import parse_skill_file
        from deerflow.skills.types import SkillCategory

        skill_file = self._write_skill(
            tmp_path,
            'name: erp-report\ndescription: d\nrequired-secrets:\n  - "bad name!"\n  - GOOD_TOKEN',
        )
        skill = parse_skill_file(skill_file, SkillCategory.CUSTOM)
        # The malformed entry is dropped; the valid one survives — one bad
        # declaration must not nuke the whole skill.
        assert [s.name for s in skill.required_secrets] == ["GOOD_TOKEN"]
