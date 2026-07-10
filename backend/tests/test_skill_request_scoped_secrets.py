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

    def test_env_path_uses_hard_timeout_not_no_change_timeout(self, sandbox):
        """The env path routes through bash.exec which exposes no idle/no-change
        timeout; it must use the dedicated wall-clock ``_DEFAULT_HARD_TIMEOUT``,
        not the legacy idle constant (same numeric value today, but distinct
        semantics so a future change to one does not silently alter the other)."""
        from deerflow.community.aio_sandbox.aio_sandbox import AioSandbox

        sandbox._client.bash.exec = MagicMock(return_value=SimpleNamespace(data=SimpleNamespace(stdout="ok", stderr=None)))
        sandbox.execute_command("echo hi", env={"X": "1"})
        _, kwargs = sandbox._client.bash.exec.call_args
        assert kwargs["hard_timeout"] == AioSandbox._DEFAULT_HARD_TIMEOUT
        assert AioSandbox._DEFAULT_HARD_TIMEOUT != AioSandbox._DEFAULT_NO_CHANGE_TIMEOUT or (
            # Same numeric value is fine today; the contract is that they are
            # named independently so the two call sites evolve independently.
            AioSandbox._DEFAULT_HARD_TIMEOUT == AioSandbox._DEFAULT_NO_CHANGE_TIMEOUT
        )

    def test_env_path_retries_on_error_observation_signature(self, sandbox):
        """The env path shares the legacy persistent-shell recovery contract: if
        the (unlikely, fresh-session) corruption marker appears, the call is
        retried rather than returned verbatim."""
        from deerflow.community.aio_sandbox.aio_sandbox import _ERROR_OBSERVATION_SIGNATURE

        corrupted = SimpleNamespace(data=SimpleNamespace(stdout=_ERROR_OBSERVATION_SIGNATURE, stderr=None))
        clean = SimpleNamespace(data=SimpleNamespace(stdout="recovered", stderr=None))
        sandbox._client.bash.exec = MagicMock(side_effect=[corrupted, clean])
        out = sandbox.execute_command("script", env={"TOK": "v"})
        assert sandbox._client.bash.exec.call_count == 2
        assert "recovered" in out
        assert _ERROR_OBSERVATION_SIGNATURE not in out


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
            # Connection-string credentials (no KEY/SECRET/TOKEN substring) — these
            # routinely embed a password, e.g. postgresql://user:pw@host/db.
            "DATABASE_URL",
            "REDIS_URL",
            "MONGODB_URI",
            "AMQP_URL",
            "SENTRY_DSN",
            "POSTGRES_DSN",
            "CONN_STR",
            "GH_PAT",
            # Password vars for services whose connection strings are already blocked
            # above. These carry no KEY/SECRET/TOKEN/PASSWORD/PASSWD substring, and a
            # blanket ``*PWD*`` / ``*AUTH*`` pattern would strip benign vars (``PWD``,
            # ``OLDPWD``), so they need exact entries.
            "MYSQL_PWD",  # read directly by mysql / libmysqlclient
            "REDISCLI_AUTH",  # read directly by redis-cli
            "REDIS_AUTH",
            # Abbreviated ``_PASS`` password vars: value-bearing plaintext passwords
            # that the full-spelling ``*PASSWORD*`` / ``*PASSWD*`` patterns miss.
            "DB_PASS",
            "SMTP_PASS",
            "MYSQL_PASS",
            "REDIS_PASS",
            "FTP_PASS",
            "MAIL_PASS",
            # Postgres file-based credential sources read by libpq/psql with no flag,
            # the direct analog of MYSQL_PWD/REDISCLI_AUTH above. PGPASSFILE names a
            # .pgpass (host:port:db:user:password); PGSERVICEFILE names a
            # pg_service.conf that may carry a password field.
            "PGPASSFILE",
            "PGSERVICEFILE",
            # Credential *helpers*: each names a program that dispenses a credential
            # on demand. Inheriting the pointer is the same leak class as inheriting
            # the value, so ``*PASS*`` scrubbing them is intended. Pinned here so the
            # behaviour is a deliberate decision rather than a side effect of the
            # pattern's shape.
            "GIT_ASKPASS",
            "SSH_ASKPASS",
            "SUDO_ASKPASS",
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
            "OLDPWD",
            "TMPDIR",
            "VIRTUAL_ENV",
            "PYTHONPATH",
            "DEERFLOW_PLAIN_VAR",
            # Not a blanket *URL* block: a benign service URL a skill may legitimately
            # read is not treated as a credential.
            "NEXT_PUBLIC_BASE_URL",
            "SERVICE_ENDPOINT",
        ],
    )
    def test_benign_names_are_allowed(self, name):
        """Names here must survive the scrub.

        Note what this list does *not* contain: any name carrying a ``PASS``
        substring. That is deliberate, not an oversight — ``*PASS*`` scrubs every
        such name, including the ``*_ASKPASS`` credential helpers pinned in
        ``test_secret_like_names_are_blocked`` above. Over-scrubbing is this
        module's fail-safe direction; a skill that needs a scrubbed name declares
        it via ``required-secrets``. ``PWD``/``OLDPWD`` are the boundary this list
        does pin: they carry no ``PASS`` substring and must never be stripped.
        """
        from deerflow.sandbox.env_policy import is_blocked_env_name

        assert is_blocked_env_name(name) is False

    def test_db_password_vars_do_not_reach_the_subprocess_env(self, monkeypatch):
        """The URL forms are scrubbed; the password vars for the same services must be too.

        ``mysql`` reads ``MYSQL_PWD`` and ``redis-cli`` reads ``REDISCLI_AUTH`` as the
        password with no further configuration, so inheriting them hands a skill
        subprocess the credential the connection-string block already withholds.
        """
        from deerflow.sandbox.env_policy import build_sandbox_env

        monkeypatch.setenv("MYSQL_URL", "mysql://user:pw@host/db")
        monkeypatch.setenv("MYSQL_PWD", "prod-db-password")
        monkeypatch.setenv("REDISCLI_AUTH", "prod-redis-auth")
        env = build_sandbox_env()
        assert "MYSQL_URL" not in env
        assert "MYSQL_PWD" not in env
        assert "REDISCLI_AUTH" not in env
        assert env.get("PWD")  # the working directory must survive the added entries

    def test_injection_still_wins_for_the_newly_blocked_names(self, monkeypatch):
        """``required-secrets`` stays the escape hatch for the names added here.

        The request-scoped value must also override the host's, which is the
        per-user-key-overrides-shared-key case from #3861.
        """
        from deerflow.sandbox.env_policy import build_sandbox_env

        monkeypatch.setenv("MYSQL_PWD", "host-value-must-not-leak")
        env = build_sandbox_env(injected={"MYSQL_PWD": "request-scoped-value"})
        assert env["MYSQL_PWD"] == "request-scoped-value"

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
        assert skill.required_secrets == ()

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

    def test_build_run_config_strips_caller_dunder_context_keys(self):
        """Security (#3938): the harness writes private ``__``-prefixed keys into
        ``runtime.context`` (binding sources, active-secret set, run journal). A
        caller must not be able to seed them via ``config.context`` and forge
        internal state — they are stripped at the gateway boundary."""
        from app.gateway.services import build_run_config

        config = build_run_config(
            "thread-1",
            {"context": {"secrets": {"ERP_TOKEN": "v"}, "__slash_skill_secret_source": {"path": "x"}, "__active_skill_secrets": {"ADMIN": "stolen"}}},
            None,
        )
        assert config["context"]["secrets"] == {"ERP_TOKEN": "v"}
        assert "__slash_skill_secret_source" not in config["context"]
        assert "__active_skill_secrets" not in config["context"]

    def test_extract_request_secrets_filters_non_string_pairs(self):
        from deerflow.runtime.secret_context import extract_request_secrets

        assert extract_request_secrets({"secrets": {"A": "x", "B": 123, 4: "y"}}) == {"A": "x"}

    def test_extract_request_secrets_missing_or_malformed(self):
        from deerflow.runtime.secret_context import extract_request_secrets

        assert extract_request_secrets({}) == {}
        assert extract_request_secrets({"secrets": "not-a-dict"}) == {}
        assert extract_request_secrets(None) == {}


def _make_secret_skill(tmp_path: Path, name: str, required_secrets, *, enabled: bool = True, secrets_autonomous: bool = True):
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
        enabled=enabled,
        required_secrets=tuple(required_secrets),
        secrets_autonomous=secrets_autonomous,
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

    def test_caller_secret_wins_over_host_value_of_same_name(self, tmp_path, monkeypatch):
        """A skill may declare a name that also exists in the host env (e.g. a
        per-user key overriding a shared platform key — the #3861 use case). The
        skill receives the CALLER's value (from context.secrets), never the host's:
        the inherited host value is scrubbed and the caller's value is injected on
        top. There is therefore no host-credential harvest to guard against."""
        from deerflow.runtime.secret_context import read_active_secrets
        from deerflow.sandbox.env_policy import build_sandbox_env

        monkeypatch.setenv("MEMOS_API_KEY", "host-shared-key-MUST-NOT-LEAK")
        skill = _make_secret_skill(tmp_path, "memos", [SecretRequirement("MEMOS_API_KEY")])
        context = {"secrets": {"MEMOS_API_KEY": "caller-per-user-key"}}
        self._activate(tmp_path, monkeypatch, skill, context)

        injected = read_active_secrets(context)
        assert injected == {"MEMOS_API_KEY": "caller-per-user-key"}  # caller's value injected

        # The subprocess env gets the caller's value; the host's value is scrubbed.
        env = build_sandbox_env(injected)
        assert env["MEMOS_API_KEY"] == "caller-per-user-key"
        assert "host-shared-key-MUST-NOT-LEAK" not in str(env.values())

    def test_undeclared_host_secret_is_scrubbed_not_harvested(self, tmp_path, monkeypatch):
        """If a skill does NOT declare a host credential, the inherited value is
        scrubbed — a skill can never read a platform credential it wasn't given."""
        from deerflow.sandbox.env_policy import build_sandbox_env

        monkeypatch.setenv("OPENAI_API_KEY", "host-key-do-not-harvest")
        env = build_sandbox_env(None)
        assert "OPENAI_API_KEY" not in env

    def test_activation_fires_after_input_sanitization_wrapping(self, tmp_path, monkeypatch):
        """Integration: in the real chain InputSanitizationMiddleware wraps the user
        message in ``--- BEGIN USER INPUT ---`` markers before SkillActivationMiddleware
        sees it. Slash activation (and therefore secret resolution) must still fire — it
        relies on the original content being recoverable. Regression for the gateway
        path where no upload preserved it."""
        from deerflow.agents.middlewares import skill_activation_middleware as mw
        from deerflow.agents.middlewares.input_sanitization_middleware import InputSanitizationMiddleware
        from deerflow.agents.middlewares.skill_activation_middleware import SkillActivationMiddleware
        from deerflow.config.app_config import AppConfig, reset_app_config, set_app_config
        from deerflow.runtime.secret_context import read_active_secrets

        skill = _make_secret_skill(tmp_path, "erp-report", [SecretRequirement("ERP_TOKEN")])
        storage = SimpleNamespace(
            load_skills=lambda *, enabled_only: [skill],
            get_container_root=lambda: "/mnt/skills",
            get_skills_root_path=lambda: tmp_path,
        )
        monkeypatch.setattr(mw, "get_or_new_skill_storage", lambda **kwargs: storage)

        context = {"secrets": {"ERP_TOKEN": "tok-xyz"}}
        request = ModelRequest(
            model=object(),
            messages=[HumanMessage(content="/erp-report pull it", id="m1")],
            state={"messages": []},
            runtime=SimpleNamespace(context=context),
        )
        # The sanitizer loads enabled skills during wrap, so keep a stub app config
        # in place for the whole composed call.
        set_app_config(AppConfig.model_validate({"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}}))
        try:
            sanitizer = InputSanitizationMiddleware()
            skill_mw = SkillActivationMiddleware()

            # Compose in real order: sanitizer (outer) -> skill activation (inner) -> model.
            def skill_layer(req):
                return skill_mw.wrap_model_call(req, lambda r: AIMessage(content="ok"))

            sanitizer.wrap_model_call(request, skill_layer)
        finally:
            reset_app_config()

        assert read_active_secrets(context) == {"ERP_TOKEN": "tok-xyz"}

    def test_prior_activation_secrets_cleared_when_next_skill_declares_none(self, tmp_path, monkeypatch):
        """A later skill in the same run never inherits an earlier skill's secrets.
        Turn 1 activates /skill-a (declares A_TOKEN, caller supplies it) → injected.
        Turn 2 activates /skill-b (declares nothing) → A_TOKEN must be cleared so
        bash in skill-b's turn cannot receive a value it never declared."""
        from deerflow.agents.middlewares import skill_activation_middleware as mw
        from deerflow.agents.middlewares.skill_activation_middleware import SkillActivationMiddleware
        from deerflow.runtime.secret_context import read_active_secrets

        skill_a = _make_secret_skill(tmp_path, "skill-a", [SecretRequirement("A_TOKEN")])
        skill_b = _make_secret_skill(tmp_path, "skill-b", [])

        def _storage(skills):
            return SimpleNamespace(
                load_skills=lambda *, enabled_only: skills,
                get_container_root=lambda: "/mnt/skills",
                get_skills_root_path=lambda: tmp_path,
            )

        context = {"secrets": {"A_TOKEN": "v-a"}}

        monkeypatch.setattr(mw, "get_or_new_skill_storage", lambda **kwargs: _storage([skill_a]))
        SkillActivationMiddleware().wrap_model_call(
            ModelRequest(
                model=object(),
                messages=[HumanMessage(content="/skill-a go", id="m1")],
                state={"messages": []},
                runtime=SimpleNamespace(context=context),
            ),
            lambda r: AIMessage(content="ok"),
        )
        assert read_active_secrets(context) == {"A_TOKEN": "v-a"}

        monkeypatch.setattr(mw, "get_or_new_skill_storage", lambda **kwargs: _storage([skill_b]))
        SkillActivationMiddleware().wrap_model_call(
            ModelRequest(
                model=object(),
                messages=[HumanMessage(content="/skill-b go", id="m2")],
                state={"messages": []},
                runtime=SimpleNamespace(context=context),
            ),
            lambda r: AIMessage(content="ok"),
        )
        assert read_active_secrets(context) == {}

    def test_prior_activation_secrets_cleared_when_caller_omits_required(self, tmp_path, monkeypatch):
        """Even when the next skill DOES declare a required secret, if the caller
        omits it the prior skill's value must not linger — the injection set ends
        up empty, not stale."""
        from deerflow.agents.middlewares import skill_activation_middleware as mw
        from deerflow.agents.middlewares.skill_activation_middleware import SkillActivationMiddleware
        from deerflow.runtime.secret_context import read_active_secrets

        skill = _make_secret_skill(tmp_path, "erp", [SecretRequirement("ERP_TOKEN")])
        storage = SimpleNamespace(
            load_skills=lambda *, enabled_only: [skill],
            get_container_root=lambda: "/mnt/skills",
            get_skills_root_path=lambda: tmp_path,
        )
        monkeypatch.setattr(mw, "get_or_new_skill_storage", lambda **kwargs: storage)

        # Turn 1: caller supplies ERP_TOKEN → injected.
        context = {"secrets": {"ERP_TOKEN": "tok-1"}}
        mw_inst = SkillActivationMiddleware()
        mw_inst.wrap_model_call(
            ModelRequest(
                model=object(),
                messages=[HumanMessage(content="/erp go", id="m1")],
                state={"messages": []},
                runtime=SimpleNamespace(context=context),
            ),
            lambda r: AIMessage(content="ok"),
        )
        assert read_active_secrets(context) == {"ERP_TOKEN": "tok-1"}

        # Turn 2: caller omits ERP_TOKEN → prior value cleared, set empty (not stale).
        context2 = {"secrets": {}}
        mw_inst.wrap_model_call(
            ModelRequest(
                model=object(),
                messages=[HumanMessage(content="/erp again", id="m2")],
                state={"messages": []},
                runtime=SimpleNamespace(context=context2),
            ),
            lambda r: AIMessage(content="ok"),
        )
        assert read_active_secrets(context2) == {}


def _skill_context_entry(skill) -> dict:
    return {
        "name": skill.name,
        "path": f"/mnt/skills/{skill.category}/{skill.name}/SKILL.md",
        "description": skill.description,
        "loaded_at": 0,
    }


class TestInContextBindsSecrets:
    """Binding point A+ (issue #3914 gap 1): a skill the model loaded earlier in
    the thread (tracked by ``ThreadState.skill_context``) keeps receiving its
    declared secrets on later turns — without a fresh ``/slash`` — as long as
    the caller supplies the values on the current request. Authorization stays
    three-gated regardless of activation style: skill enabled by the operator,
    values supplied per-request by the caller, names declared in frontmatter.
    """

    def _run_call(self, tmp_path, monkeypatch, skills, *, context, skill_context=None, message="continue the report", available_skills=None, middleware=None, container_root="/mnt/skills"):
        from deerflow.agents.middlewares import skill_activation_middleware as mw
        from deerflow.agents.middlewares.skill_activation_middleware import SkillActivationMiddleware

        storage = SimpleNamespace(
            load_skills=lambda *, enabled_only: list(skills),
            get_container_root=lambda: container_root,
            get_skills_root_path=lambda: tmp_path,
        )
        monkeypatch.setattr(mw, "get_or_new_skill_storage", lambda **kwargs: storage)
        mw_inst = middleware or SkillActivationMiddleware(available_skills=available_skills)
        mw_inst.wrap_model_call(
            ModelRequest(
                model=object(),
                messages=[HumanMessage(content=message, id="m1")],
                state={"messages": [], "skill_context": skill_context or []},
                runtime=SimpleNamespace(context=context),
            ),
            lambda r: AIMessage(content="ok"),
        )
        return mw_inst

    def test_in_context_skill_binds_secrets_without_slash(self, tmp_path, monkeypatch):
        from deerflow.runtime.secret_context import read_active_secrets

        skill = _make_secret_skill(tmp_path, "erp-report", [SecretRequirement("ERP_TOKEN")])
        context = {"secrets": {"ERP_TOKEN": "tok-123", "UNRELATED": "x"}}
        self._run_call(tmp_path, monkeypatch, [skill], context=context, skill_context=[_skill_context_entry(skill)])

        assert read_active_secrets(context) == {"ERP_TOKEN": "tok-123"}

    def test_binding_clears_when_skill_evicted_from_context(self, tmp_path, monkeypatch):
        """Long-lived binding follows skill_context membership exactly: once the
        entry is evicted (capacity) the injection disappears on the next call."""
        from deerflow.runtime.secret_context import read_active_secrets

        skill = _make_secret_skill(tmp_path, "erp-report", [SecretRequirement("ERP_TOKEN")])
        context = {"secrets": {"ERP_TOKEN": "tok-123"}}
        mw_inst = self._run_call(tmp_path, monkeypatch, [skill], context=context, skill_context=[_skill_context_entry(skill)])
        assert read_active_secrets(context) == {"ERP_TOKEN": "tok-123"}

        self._run_call(tmp_path, monkeypatch, [skill], context=context, skill_context=[], middleware=mw_inst)
        assert read_active_secrets(context) == {}

    def test_disabled_skill_in_context_not_bound(self, tmp_path, monkeypatch):
        from deerflow.runtime.secret_context import read_active_secrets

        skill = _make_secret_skill(tmp_path, "erp-report", [SecretRequirement("ERP_TOKEN")], enabled=False)
        context = {"secrets": {"ERP_TOKEN": "tok-123"}}
        self._run_call(tmp_path, monkeypatch, [skill], context=context, skill_context=[_skill_context_entry(skill)])

        assert read_active_secrets(context) == {}

    def test_skill_outside_agent_allowlist_not_bound(self, tmp_path, monkeypatch):
        from deerflow.runtime.secret_context import read_active_secrets

        skill = _make_secret_skill(tmp_path, "erp-report", [SecretRequirement("ERP_TOKEN")])
        context = {"secrets": {"ERP_TOKEN": "tok-123"}}
        self._run_call(
            tmp_path,
            monkeypatch,
            [skill],
            context=context,
            skill_context=[_skill_context_entry(skill)],
            available_skills={"some-other-skill"},
        )

        assert read_active_secrets(context) == {}

    def test_secrets_autonomous_false_blocks_in_context_but_not_slash(self, tmp_path, monkeypatch):
        """The per-skill opt-out keeps explicit-activation ceremony available for
        high-sensitivity skills: in-context binding is refused, slash still works."""
        from deerflow.runtime.secret_context import read_active_secrets

        skill = _make_secret_skill(tmp_path, "erp-report", [SecretRequirement("ERP_TOKEN")], secrets_autonomous=False)

        context = {"secrets": {"ERP_TOKEN": "tok-123"}}
        self._run_call(tmp_path, monkeypatch, [skill], context=context, skill_context=[_skill_context_entry(skill)])
        assert read_active_secrets(context) == {}

        slash_context = {"secrets": {"ERP_TOKEN": "tok-123"}}
        self._run_call(tmp_path, monkeypatch, [skill], context=slash_context, message="/erp-report go")
        assert read_active_secrets(slash_context) == {"ERP_TOKEN": "tok-123"}

    def test_slash_and_in_context_sources_merge(self, tmp_path, monkeypatch):
        from deerflow.runtime.secret_context import read_active_secrets

        loaded = _make_secret_skill(tmp_path, "erp-report", [SecretRequirement("ERP_TOKEN")])
        slashed = _make_secret_skill(tmp_path, "crm-sync", [SecretRequirement("CRM_TOKEN")])
        context = {"secrets": {"ERP_TOKEN": "tok-erp", "CRM_TOKEN": "tok-crm"}}
        self._run_call(
            tmp_path,
            monkeypatch,
            [loaded, slashed],
            context=context,
            skill_context=[_skill_context_entry(loaded)],
            message="/crm-sync push the numbers",
        )

        assert read_active_secrets(context) == {"ERP_TOKEN": "tok-erp", "CRM_TOKEN": "tok-crm"}

    def test_forged_slash_source_cannot_bypass_gates(self, tmp_path, monkeypatch):
        """Security (#3938): `runtime.context` is caller-mergeable, so a client can
        forge `__slash_skill_secret_source`. The slash source is re-validated
        against the live registry (enabled + allowlist), so a forged source naming
        a non-existent skill binds nothing — no gate bypass."""
        from deerflow.runtime.secret_context import _SLASH_SECRET_SOURCE_KEY, read_active_secrets

        context = {
            "secrets": {"ADMIN_TOKEN": "stolen"},
            _SLASH_SECRET_SOURCE_KEY: {"path": "/mnt/skills/custom/attacker/SKILL.md", "skill_name": "attacker", "requirements": [["ADMIN_TOKEN", False]]},
        }
        self._run_call(tmp_path, monkeypatch, [], context=context, message="no slash here")
        assert read_active_secrets(context) == {}

    def test_forged_slash_source_ignores_caller_requirements_and_allowlist(self, tmp_path, monkeypatch):
        """Even if a forged path resolves to a real skill, the caller's forged
        requirements are ignored (only the registry skill's own declared secrets
        bind) and the allowlist still applies."""
        from deerflow.runtime.secret_context import _SLASH_SECRET_SOURCE_KEY, read_active_secrets

        skill = _make_secret_skill(tmp_path, "erp-report", [SecretRequirement("ERP_TOKEN")])
        context = {
            "secrets": {"ADMIN_TOKEN": "stolen", "ERP_TOKEN": "ok"},
            _SLASH_SECRET_SOURCE_KEY: {"path": "/mnt/skills/custom/erp-report/SKILL.md", "requirements": [["ADMIN_TOKEN", False]]},
        }
        self._run_call(tmp_path, monkeypatch, [skill], context=context, available_skills={"other"})
        assert read_active_secrets(context) == {}

    def test_malformed_slash_source_does_not_crash(self, tmp_path, monkeypatch):
        """Robustness (#3938): a forged malformed slash source must fail closed
        (bind nothing), never raise and 500 the run."""
        from deerflow.runtime.secret_context import _SLASH_SECRET_SOURCE_KEY, read_active_secrets

        skill = _make_secret_skill(tmp_path, "erp-report", [SecretRequirement("ERP_TOKEN")])
        for bad in ({"requirements": [["X"]]}, {"requirements": "abc"}, {"path": 123}, "not-a-dict", {"path": ["a"]}, {}):
            context = {"secrets": {"ERP_TOKEN": "v"}, _SLASH_SECRET_SOURCE_KEY: bad}
            self._run_call(tmp_path, monkeypatch, [skill], context=context, message="x")
            assert read_active_secrets(context) == {}, f"bad={bad!r}"

    def test_trailing_slash_container_root_still_binds(self, tmp_path, monkeypatch):
        """Latent bug (#3938): a non-canonical container_path (trailing slash) must
        not silently disable in-context binding — paths are normalized both sides."""
        from deerflow.runtime.secret_context import read_active_secrets

        skill = _make_secret_skill(tmp_path, "erp-report", [SecretRequirement("ERP_TOKEN")])
        context = {"secrets": {"ERP_TOKEN": "tok-123"}}
        entry = {"name": "erp-report", "path": "/mnt/skills/custom/erp-report/SKILL.md", "description": "d", "loaded_at": 0}
        self._run_call(tmp_path, monkeypatch, [skill], context=context, skill_context=[entry], container_root="/mnt/skills/")
        assert read_active_secrets(context) == {"ERP_TOKEN": "tok-123"}

    def test_shadowing_name_does_not_bind_unread_skill(self, tmp_path, monkeypatch):
        """Confused-deputy guard: a custom skill may shadow a same-named public
        one (load_skills de-dupes by name, custom wins). A thread that read the
        PUBLIC foo (no declared secrets) must NOT bind the CUSTOM foo's declared
        secret — matching is by exact container path, never by name."""
        from deerflow.runtime.secret_context import read_active_secrets

        # Registry exposes only the custom foo (name de-dup, custom wins); the
        # model read the public foo, whose path differs.
        custom_foo = _make_secret_skill(tmp_path, "foo", [SecretRequirement("ERP_TOKEN")])
        context = {"secrets": {"ERP_TOKEN": "tok-123"}}
        entry = {
            "name": "foo",
            "path": "/mnt/skills/public/foo/SKILL.md",  # the PUBLIC one the model actually read
            "description": "d",
            "loaded_at": 0,
        }
        self._run_call(tmp_path, monkeypatch, [custom_foo], context=context, skill_context=[entry])

        assert read_active_secrets(context) == {}

    def test_stale_path_does_not_fall_back_to_name(self, tmp_path, monkeypatch):
        """A skill_context path that no longer resolves must not degrade to a
        name match — it simply does not bind."""
        from deerflow.runtime.secret_context import read_active_secrets

        skill = _make_secret_skill(tmp_path, "erp-report", [SecretRequirement("ERP_TOKEN")])
        context = {"secrets": {"ERP_TOKEN": "tok-123"}}
        entry = {
            "name": "erp-report",
            "path": "/mnt/skills/custom/erp-report-OLD-PATH/SKILL.md",
            "description": "d",
            "loaded_at": 0,
        }
        self._run_call(tmp_path, monkeypatch, [skill], context=context, skill_context=[entry])

        assert read_active_secrets(context) == {}

    def test_no_caller_secrets_means_no_binding(self, tmp_path, monkeypatch):
        """The supply gate: without caller-provided values on THIS request there
        is nothing to inject, no matter what is in skill_context."""
        from deerflow.runtime.secret_context import read_active_secrets

        skill = _make_secret_skill(tmp_path, "erp-report", [SecretRequirement("ERP_TOKEN")])
        context = {"secrets": {}}
        self._run_call(tmp_path, monkeypatch, [skill], context=context, skill_context=[_skill_context_entry(skill)])

        assert read_active_secrets(context) == {}

    def test_binding_change_recorded_in_audit_journal_names_only(self, tmp_path, monkeypatch):
        skill = _make_secret_skill(tmp_path, "erp-report", [SecretRequirement("ERP_TOKEN")])
        journal = MagicMock()
        context = {"secrets": {"ERP_TOKEN": "tok-secret-value"}, "__run_journal": journal}
        self._run_call(tmp_path, monkeypatch, [skill], context=context, skill_context=[_skill_context_entry(skill)])

        bind_calls = [call for call in journal.record_middleware.call_args_list if call.kwargs.get("action") == "bind_secrets"]
        assert len(bind_calls) == 1
        changes = bind_calls[0].kwargs["changes"]
        assert changes["skills"] == ["erp-report"]
        assert changes["secrets"] == ["ERP_TOKEN"]
        # Values must never reach the audit journal.
        assert "tok-secret-value" not in str(bind_calls[0])

    def test_slash_binding_persists_across_model_calls_in_same_run(self, tmp_path, monkeypatch):
        """#3861 semantics preserved under per-call recompute: after the single
        activation call, the tool loop issues more model calls without a fresh
        slash — the binding must survive on the shared run context."""
        from deerflow.runtime.secret_context import read_active_secrets

        skill = _make_secret_skill(tmp_path, "erp-report", [SecretRequirement("ERP_TOKEN")])
        context = {"secrets": {"ERP_TOKEN": "tok-123"}}
        mw_inst = self._run_call(tmp_path, monkeypatch, [skill], context=context, message="/erp-report go")
        assert read_active_secrets(context) == {"ERP_TOKEN": "tok-123"}

        # Later model call in the SAME run (same context object): no slash in the
        # latest message, skill never entered skill_context (slash injects the
        # body directly, no read_file happens).
        self._run_call(tmp_path, monkeypatch, [skill], context=context, message="tool loop continues", middleware=mw_inst)
        assert read_active_secrets(context) == {"ERP_TOKEN": "tok-123"}

    def test_unchanged_binding_not_re_recorded(self, tmp_path, monkeypatch):
        skill = _make_secret_skill(tmp_path, "erp-report", [SecretRequirement("ERP_TOKEN")])
        journal = MagicMock()
        context = {"secrets": {"ERP_TOKEN": "tok-1"}, "__run_journal": journal}
        mw_inst = self._run_call(tmp_path, monkeypatch, [skill], context=context, skill_context=[_skill_context_entry(skill)])
        self._run_call(tmp_path, monkeypatch, [skill], context=context, skill_context=[_skill_context_entry(skill)], middleware=mw_inst)

        bind_calls = [call for call in journal.record_middleware.call_args_list if call.kwargs.get("action") == "bind_secrets"]
        assert len(bind_calls) == 1


class TestSecretsAutonomousParsing:
    """Frontmatter ``secrets-autonomous`` controls in-context (autonomous) binding."""

    def _parse(self, tmp_path, frontmatter_extra: str):
        from deerflow.skills.parser import parse_skill_file
        from deerflow.skills.types import SkillCategory

        skill_dir = tmp_path / "erp-report"
        skill_dir.mkdir()
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text(
            f"""---
name: erp-report
description: Pull an ERP report.
required-secrets:
  - ERP_TOKEN
{frontmatter_extra}---

Body.
""",
            encoding="utf-8",
        )
        return parse_skill_file(skill_file, SkillCategory.CUSTOM)

    def test_defaults_to_true(self, tmp_path):
        skill = self._parse(tmp_path, "")
        assert skill is not None
        assert skill.secrets_autonomous is True

    def test_explicit_false(self, tmp_path):
        skill = self._parse(tmp_path, "secrets-autonomous: false\n")
        assert skill is not None
        assert skill.secrets_autonomous is False

    def test_malformed_value_fails_closed(self, tmp_path, caplog):
        """A non-boolean value disables autonomous binding (the safer direction)
        instead of silently enabling it."""
        skill = self._parse(tmp_path, 'secrets-autonomous: "yes please"\n')
        assert skill is not None
        assert skill.secrets_autonomous is False


class TestBashToolInjectsActiveSecrets:
    """The bash tool forwards the per-run injection set to execute_command(env=...)."""

    def _run_bash(self, context):
        from deerflow.sandbox import tools as tools_mod

        captured = {}

        class FakeSandbox:
            def execute_command(self, command, env=None, timeout=None):
                captured["env"] = env
                captured["timeout"] = timeout
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

    def test_local_bash_forwards_env_and_timeout(self, monkeypatch):
        from deerflow.sandbox import tools as tools_mod

        captured = {}

        class FakeSandbox:
            def execute_command(self, command, env=None, timeout=None):
                captured["command"] = command
                captured["env"] = env
                captured["timeout"] = timeout
                return "done"

        runtime = SimpleNamespace(
            context={"__active_skill_secrets": {"ERP_TOKEN": "tok-456"}},
            state={"sandbox": {"sandbox_id": "local:1"}},
        )
        thread_data = {"workspace_path": "/tmp/ws", "cwd": "/mnt/user-data/workspace"}
        fake_cfg = SimpleNamespace(sandbox=SimpleNamespace(bash_output_max_chars=321, bash_command_timeout=42))
        with (
            patch.object(tools_mod, "ensure_sandbox_initialized", return_value=FakeSandbox()),
            patch.object(tools_mod, "is_local_sandbox", return_value=True),
            patch.object(tools_mod, "is_host_bash_allowed", return_value=True),
            patch.object(tools_mod, "ensure_thread_directories_exist", return_value=None),
            patch.object(tools_mod, "get_thread_data", return_value=thread_data),
            patch.object(tools_mod, "validate_local_bash_command_paths", return_value=None),
            patch.object(tools_mod, "replace_virtual_paths_in_command", side_effect=lambda command, td: command),
            patch.object(tools_mod, "_apply_cwd_prefix", side_effect=lambda command, td: command),
            patch("deerflow.config.app_config.get_app_config", return_value=fake_cfg),
        ):
            out = tools_mod.bash_tool.func(runtime, "run local skill", "echo hi")

        assert out == "done"
        assert captured["command"] == "echo hi"
        assert captured["env"] == {"ERP_TOKEN": "tok-456"}
        assert captured["timeout"] == 42


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

    def test_redact_config_secrets_strips_from_persisted_config(self):
        # The run-record persistence + run API echo the raw request config; the
        # stored/echoed copy must not carry secrets (verifier blocker), while the
        # live config used to drive the run keeps them.
        from deerflow.runtime.secret_context import redact_config_secrets

        config = {"context": {"secrets": {"ERP_TOKEN": _SECRET}, "thread_id": "t", "model_name": "m"}, "recursion_limit": 100}
        redacted = redact_config_secrets(config)
        assert _SECRET not in str(redacted)
        assert redacted["context"]["thread_id"] == "t"
        assert redacted["context"]["model_name"] == "m"
        assert "secrets" not in redacted["context"]
        # Original is untouched (live config still has secrets).
        assert config["context"]["secrets"] == {"ERP_TOKEN": _SECRET}

    def test_redact_config_secrets_handles_none_and_no_context(self):
        from deerflow.runtime.secret_context import redact_config_secrets

        assert redact_config_secrets(None) is None
        assert redact_config_secrets({"configurable": {"thread_id": "t"}}) == {"configurable": {"thread_id": "t"}}

    def test_stdout_surface_redacted(self):
        from deerflow.sandbox.tools import mask_secret_values

        leaked = f"DEBUG: token is {_SECRET} done"
        masked = mask_secret_values(leaked, {"ERP_TOKEN": _SECRET})
        assert _SECRET not in masked
        assert "[redacted]" in masked

    def test_short_secret_values_not_masked(self):
        """Values below the minimum length floor are skipped — redacting a 2-char
        value would shred unrelated bytes (exit codes, timestamps, sizes) of tool
        output. The secret is still injected into the subprocess; only the output
        mask skips it."""
        from deerflow.sandbox.tools import mask_secret_values

        # A short value must not be replaced everywhere in the output.
        out = "exit code: 42\nrows: 42\n"
        masked = mask_secret_values(out, {"REGION": "42"})
        assert masked == out  # unchanged — short value left intact

        # A long value is still redacted as before.
        long_secret = "sk-erp-long-enough-token-value"
        masked_long = mask_secret_values(f"token={long_secret}", {"ERP_TOKEN": long_secret})
        assert long_secret not in masked_long
        assert "[redacted]" in masked_long


@pytest.mark.skipif(__import__("os").name == "nt", reason="POSIX shell semantics")
class TestEndToEndRealSubprocess:
    """End-to-end across the real chain (no sandbox mock): activation resolves the
    secret, a REAL LocalSandbox subprocess receives it via env, the value lands in
    a file but is redacted from the returned output, and a later un-injected call
    cannot see it."""

    def test_secret_reaches_real_subprocess_only_via_env_and_is_scoped(self, tmp_path, monkeypatch):
        from deerflow.agents.middlewares import skill_activation_middleware as mw
        from deerflow.agents.middlewares.skill_activation_middleware import SkillActivationMiddleware
        from deerflow.runtime.secret_context import read_active_secrets
        from deerflow.sandbox.tools import mask_secret_values

        # 1. Activate a skill that declares ERP_TOKEN; caller supplies it in context.secrets.
        skill = _make_secret_skill(tmp_path, "erp-report", [SecretRequirement("ERP_TOKEN")])
        storage = SimpleNamespace(
            load_skills=lambda *, enabled_only: [skill],
            get_container_root=lambda: "/mnt/skills",
            get_skills_root_path=lambda: tmp_path,
        )
        monkeypatch.setattr(mw, "get_or_new_skill_storage", lambda **kwargs: storage)
        # A platform secret is present on the host and must NOT leak to the subprocess.
        monkeypatch.setenv("OPENAI_API_KEY", "sk-host-platform-secret")
        context = {"secrets": {"ERP_TOKEN": _SECRET}}
        request = ModelRequest(
            model=object(),
            messages=[HumanMessage(content="/erp-report pull report", id="m1")],
            state={"messages": []},
            runtime=SimpleNamespace(context=context),
        )
        SkillActivationMiddleware().wrap_model_call(request, lambda r: AIMessage(content="ok"))
        injected = read_active_secrets(context)
        assert injected == {"ERP_TOKEN": _SECRET}

        # 2. A REAL LocalSandbox runs a script that writes the token to a file and echoes it.
        out_file = tmp_path / "token.txt"
        sandbox = LocalSandbox(id="local")
        raw = sandbox.execute_command(
            f'printf "%s" "$ERP_TOKEN" > {out_file}; echo "leaked:$ERP_TOKEN"; echo "platform:$OPENAI_API_KEY"',
            env=injected,
        )

        # 3. The skill genuinely received the token via env (file written by the subprocess).
        assert out_file.read_text() == _SECRET
        # 4. Platform secret was scrubbed — not available to the script.
        assert "sk-host-platform-secret" not in raw
        # 5. Stdout masking redacts the echoed token before it would re-enter context.
        masked = mask_secret_values(raw, injected)
        assert _SECRET not in masked

        # 6. Per-call scope: a later command without injection cannot see the token.
        leaked = sandbox.execute_command("echo [$ERP_TOKEN]")
        assert _SECRET not in leaked
