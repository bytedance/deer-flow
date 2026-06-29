"""Tests for request-scoped secret injection into skills (issue #3861).

Covers the full feature surface:
  - Slice 1: ``Sandbox.execute_command(command, env=...)`` per-call env injection
    on both the local and AIO backends.
  - Slice 2: ``SKILL.md`` ``requires-secrets`` frontmatter parsing.
  - Slice 3: gateway carrier (``context.secrets``) and runtime-context passthrough.
  - Slice 4: activation-turn binding + ``bash`` tool injection.
  - Slice 5: the five leak surfaces (prompt / trace / checkpoint / audit / stdout).
"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from langchain.agents.middleware.types import ModelRequest
from langchain_core.messages import AIMessage, HumanMessage

from deerflow.sandbox.local.local_sandbox import LocalSandbox
from deerflow.skills.types import SecretRequirement, Skill, SkillCategory


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


class TestSecretCarrier:
    """Request-scoped secret carrier: context.secrets → runtime.context (Slice 3)."""

    def test_build_run_config_keeps_secrets_in_context_not_configurable(self):
        from app.gateway.services import build_run_config

        config = build_run_config("thread-1", {"context": {"secrets": {"ERP_TOKEN": "v"}}}, None)
        assert config["context"]["secrets"] == {"ERP_TOKEN": "v"}
        # Secrets must never be mirrored into configurable (which legacy readers
        # and some trace backends surface).
        assert "secrets" not in config.get("configurable", {})

    def test_runtime_context_carries_secrets(self):
        from deerflow.runtime.runs.worker import _build_runtime_context

        ctx = _build_runtime_context("t", "r", {"secrets": {"ERP_TOKEN": "v"}})
        assert ctx["secrets"] == {"ERP_TOKEN": "v"}

    def test_extract_request_secrets_filters_non_string_pairs(self):
        from deerflow.runtime.secret_context import extract_request_secrets

        assert extract_request_secrets({"secrets": {"A": "x", "B": 123, 4: "y"}}) == {"A": "x"}

    def test_extract_request_secrets_missing_or_malformed(self):
        from deerflow.runtime.secret_context import extract_request_secrets

        assert extract_request_secrets({}) == {}
        assert extract_request_secrets({"secrets": "not-a-dict"}) == {}
        assert extract_request_secrets(None) == {}


class TestHostPlatformSecretGuard:
    """A skill must not be able to harvest a host platform credential (GHSA-rhgp-j443-p4rf)."""

    def test_host_platform_secret_detected(self, monkeypatch):
        from deerflow.sandbox.env_policy import is_host_platform_secret

        monkeypatch.setenv("OPENAI_API_KEY", "present-on-host")
        assert is_host_platform_secret("OPENAI_API_KEY") is True

    def test_request_token_not_a_host_secret(self, monkeypatch):
        from deerflow.sandbox.env_policy import is_host_platform_secret

        # ERP_TOKEN is secret-looking but NOT present in the host environment —
        # it is a legitimate per-request user token, the primary #3861 use case.
        monkeypatch.delenv("ERP_TOKEN", raising=False)
        assert is_host_platform_secret("ERP_TOKEN") is False


def _make_secret_skill(tmp_path: Path, name: str, required_secrets):
    skill_dir = tmp_path / name
    skill_dir.mkdir()
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(f"# {name}\n", encoding="utf-8")
    return Skill(
        name=name,
        description=f"Description for {name}",
        license="MIT",
        skill_dir=skill_dir,
        skill_file=skill_file,
        relative_path=Path(name),
        category=SkillCategory.CUSTOM,
        enabled=True,
        required_secrets=required_secrets,
    )


class TestActivationBindsSecrets:
    """Binding point A: activation turn resolves declared secrets into the per-run injection set."""

    def _activate(self, tmp_path, monkeypatch, skill, context):
        from deerflow.agents.middlewares import skill_activation_middleware as mw
        from deerflow.agents.middlewares.skill_activation_middleware import SkillActivationMiddleware

        storage = SimpleNamespace(
            load_skills=lambda *, enabled_only: [skill],
            get_container_root=lambda: "/mnt/skills",
            get_skills_root_path=lambda: tmp_path,
        )
        monkeypatch.setattr(mw, "get_or_new_skill_storage", lambda **kwargs: storage)
        middleware = SkillActivationMiddleware()
        request = ModelRequest(
            model=object(),
            messages=[HumanMessage(content=f"/{skill.name} do it", id="m1")],
            state={"messages": []},
            runtime=SimpleNamespace(context=context),
        )
        middleware.wrap_model_call(request, lambda r: AIMessage(content="ok"))

    def test_declared_secret_resolved_into_active_set(self, tmp_path, monkeypatch):
        from deerflow.runtime.secret_context import read_active_secrets

        skill = _make_secret_skill(tmp_path, "erp-report", [SecretRequirement("ERP_TOKEN")])
        context = {"secrets": {"ERP_TOKEN": "tok-123", "UNUSED": "x"}}
        self._activate(tmp_path, monkeypatch, skill, context)
        # Only the declared secret is injected — not the whole secrets bag.
        assert read_active_secrets(context) == {"ERP_TOKEN": "tok-123"}

    def test_skill_without_declaration_gets_no_injection(self, tmp_path, monkeypatch):
        from deerflow.runtime.secret_context import read_active_secrets

        skill = _make_secret_skill(tmp_path, "plain", [])
        context = {"secrets": {"ERP_TOKEN": "tok-123"}}
        self._activate(tmp_path, monkeypatch, skill, context)
        assert read_active_secrets(context) == {}

    def test_missing_required_secret_not_injected(self, tmp_path, monkeypatch):
        from deerflow.runtime.secret_context import read_active_secrets

        skill = _make_secret_skill(tmp_path, "erp-report", [SecretRequirement("ERP_TOKEN")])
        context = {"secrets": {}}  # caller provided none
        self._activate(tmp_path, monkeypatch, skill, context)
        assert read_active_secrets(context) == {}

    def test_host_platform_secret_declaration_refused(self, tmp_path, monkeypatch):
        from deerflow.runtime.secret_context import read_active_secrets

        monkeypatch.setenv("OPENAI_API_KEY", "host-key-do-not-harvest")
        skill = _make_secret_skill(tmp_path, "evil", [SecretRequirement("OPENAI_API_KEY")])
        # Even if a caller is tricked into supplying it, the guard refuses injection.
        context = {"secrets": {"OPENAI_API_KEY": "whatever"}}
        self._activate(tmp_path, monkeypatch, skill, context)
        assert "OPENAI_API_KEY" not in read_active_secrets(context)


class TestBashToolInjectsActiveSecrets:
    """The bash tool forwards the per-run injection set to execute_command(env=...)."""

    def _run_bash(self, context):
        from deerflow.sandbox import tools as tools_mod

        captured = {}

        class FakeSandbox:
            def execute_command(self, command, env=None):
                captured["env"] = env
                return "done"

        runtime = SimpleNamespace(context=context, state={"sandbox": {"sandbox_id": "aio:1"}})
        with (
            patch.object(tools_mod, "ensure_sandbox_initialized", return_value=FakeSandbox()),
            patch.object(tools_mod, "is_local_sandbox", return_value=False),
            patch.object(tools_mod, "ensure_thread_directories_exist", return_value=None),
        ):
            out = tools_mod.bash_tool.func(runtime, "run skill", "echo hi")
        return out, captured

    def test_active_secret_forwarded_as_env(self):
        out, captured = self._run_bash({"__active_skill_secrets": {"ERP_TOKEN": "tok-123"}})
        assert captured["env"] == {"ERP_TOKEN": "tok-123"}
        assert "done" in out

    def test_no_active_secret_forwards_no_env(self):
        out, captured = self._run_bash({})
        assert captured["env"] in (None, {})


_SECRET = "sk-erp-9f3c-DO-NOT-LEAK"


class TestLeakSurfaces:
    """Assert the secret value is absent from all five leak surfaces (#3861)."""

    def _activate_with_secret(self, tmp_path, monkeypatch):
        from deerflow.agents.middlewares import skill_activation_middleware as mw
        from deerflow.agents.middlewares.skill_activation_middleware import SkillActivationMiddleware

        skill = _make_secret_skill(tmp_path, "erp-report", [SecretRequirement("ERP_TOKEN")])
        storage = SimpleNamespace(
            load_skills=lambda *, enabled_only: [skill],
            get_container_root=lambda: "/mnt/skills",
            get_skills_root_path=lambda: tmp_path,
        )
        monkeypatch.setattr(mw, "get_or_new_skill_storage", lambda **kwargs: storage)

        journal_records: list[dict] = []
        journal = SimpleNamespace(record_middleware=lambda *a, **k: journal_records.append({"a": a, "k": k}))
        context = {"secrets": {"ERP_TOKEN": _SECRET}, "__run_journal": journal}
        request = ModelRequest(
            model=object(),
            messages=[HumanMessage(content="/erp-report pull report", id="m1")],
            state={"messages": []},
            runtime=SimpleNamespace(context=context),
        )
        captured = {}
        SkillActivationMiddleware().wrap_model_call(request, lambda r: captured.setdefault("messages", r.messages) or AIMessage(content="ok"))
        return context, captured["messages"], journal_records

    def test_prompt_surface_has_no_secret(self, tmp_path, monkeypatch):
        # The injected activation message (the only thing added to the prompt /
        # checkpointed messages) must not contain the secret value.
        _, messages, _ = self._activate_with_secret(tmp_path, monkeypatch)
        for m in messages:
            assert _SECRET not in str(m.content)

    def test_checkpoint_surface_separation(self, tmp_path, monkeypatch):
        # Secrets live on runtime.context, never in the graph state that gets
        # checkpointed (messages/state).
        context, messages, _ = self._activate_with_secret(tmp_path, monkeypatch)
        assert context["secrets"]["ERP_TOKEN"] == _SECRET  # present in context...
        assert _SECRET not in str([m.content for m in messages])  # ...not in state

    def test_audit_surface_has_no_secret(self, tmp_path, monkeypatch):
        _, _, journal_records = self._activate_with_secret(tmp_path, monkeypatch)
        assert journal_records, "activation should record an audit event"
        assert _SECRET not in str(journal_records)

    def test_trace_metadata_has_no_secret(self, monkeypatch):
        from deerflow.tracing import metadata as meta

        monkeypatch.setattr(meta, "get_enabled_tracing_providers", lambda: {"langfuse"})
        config = {"context": {"secrets": {"ERP_TOKEN": _SECRET}}, "metadata": {}}
        meta.inject_langfuse_metadata(config, thread_id="t", user_id="u", model_name="m")
        assert _SECRET not in str(config["metadata"])
        # And secrets were never mirrored into configurable.
        assert _SECRET not in str(config.get("configurable", {}))

    def test_redact_helper_strips_secret_keys(self):
        from deerflow.runtime.secret_context import redact_secret_context_keys

        ctx = {"thread_id": "t", "secrets": {"ERP_TOKEN": _SECRET}, "__active_skill_secrets": {"ERP_TOKEN": _SECRET}}
        redacted = redact_secret_context_keys(ctx)
        assert redacted == {"thread_id": "t"}
        assert _SECRET not in str(redacted)

    def test_stdout_surface_redacted(self):
        from deerflow.sandbox.tools import mask_secret_values

        leaked = f"DEBUG: token is {_SECRET} done"
        masked = mask_secret_values(leaked, {"ERP_TOKEN": _SECRET})
        assert _SECRET not in masked
        assert "[redacted]" in masked
