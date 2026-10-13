#!/usr/bin/env python3
"""DeerFlow Health Check (make doctor).

Checks system requirements, configuration, LLM provider, and optional
components, then prints an actionable report.

Exit codes:
  0 — all required checks passed (warnings allowed)
  1 — one or more required checks failed
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from importlib import import_module
from pathlib import Path
from typing import Literal

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

Status = Literal["ok", "warn", "fail", "skip"]
PNPM_SCRIPT_PATH = Path(__file__).resolve().with_name("pnpm.py")
FRONTEND_DIR = PNPM_SCRIPT_PATH.parent.parent / "frontend"


def _supports_color() -> bool:
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


def _c(text: str, code: str) -> str:
    if _supports_color():
        return f"\033[{code}m{text}\033[0m"
    return text


def green(t: str) -> str:
    return _c(t, "32")


def red(t: str) -> str:
    return _c(t, "31")


def yellow(t: str) -> str:
    return _c(t, "33")


def cyan(t: str) -> str:
    return _c(t, "36")


def bold(t: str) -> str:
    return _c(t, "1")


def _icon(status: Status) -> str:
    icons = {"ok": green("✓"), "warn": yellow("!"), "fail": red("✗"), "skip": "—"}
    return icons[status]


def _run(cmd: list[str]) -> str | None:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", check=True)
        return (r.stdout or r.stderr).strip()
    except Exception:
        return None


def _parse_major(version_text: str) -> int | None:
    v = version_text.lstrip("v").split(".", 1)[0]
    return int(v) if v.isdigit() else None


def _load_yaml_file(path: Path) -> dict:
    import yaml

    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError("top-level config must be a YAML mapping")
    return data


def _load_app_config(config_path: Path) -> object:
    from deerflow.config.app_config import AppConfig

    return AppConfig.from_file(str(config_path))


def _split_use_path(use: str) -> tuple[str, str] | None:
    if ":" not in use:
        return None
    module_name, attr_name = use.split(":", 1)
    if not module_name or not attr_name:
        return None
    return module_name, attr_name


def _load_json_object(path: Path) -> dict | None:
    """Load a JSON object without letting malformed CLI state abort doctor."""
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _has_non_empty_token(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


# Acceptance rules mirror backend/packages/harness/deerflow/models/credential_loader.py
# (``load_codex_cli_credential``, ``_extract_claude_code_credential`` + ``is_expired``), which
# stays the source of truth; keep the two in lockstep when the loader changes. The mirror is
# deliberate: importing the loader could consume the one-shot
# CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR handoff. Strictness differs on purpose in one
# place -- doctor rejects a whitespace-only token that the runtime's truthiness check would
# accept before failing at the provider.
def _codex_auth_file_has_access_token(path: Path) -> bool:
    data = _load_json_object(path)
    if data is None:
        return False
    tokens = data.get("tokens")
    nested_access_token = tokens.get("access_token") if isinstance(tokens, dict) else None
    return any(_has_non_empty_token(value) for value in (data.get("access_token"), data.get("token"), nested_access_token))


def _claude_credentials_file_has_access_token(path: Path) -> bool:
    data = _load_json_object(path)
    oauth = data.get("claudeAiOauth") if data is not None else None
    if not isinstance(oauth, dict) or not _has_non_empty_token(oauth.get("accessToken")):
        return False
    expires_at = oauth.get("expiresAt", 0)
    if isinstance(expires_at, bool) or not isinstance(expires_at, (int, float)):
        return False
    return expires_at <= 0 or time.time() * 1000 <= expires_at - 60_000


# ---------------------------------------------------------------------------
# Check result container
# ---------------------------------------------------------------------------


class CheckResult:
    def __init__(
        self,
        label: str,
        status: Status,
        detail: str = "",
        fix: str | None = None,
    ) -> None:
        self.label = label
        self.status = status
        self.detail = detail
        self.fix = fix

    def print(self) -> None:
        icon = _icon(self.status)
        detail_str = f"  ({self.detail})" if self.detail else ""
        print(f"  {icon} {self.label}{detail_str}")
        if self.fix:
            for line in self.fix.splitlines():
                print(f"      {cyan('→')} {line}")


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def check_python() -> CheckResult:
    v = sys.version_info
    version_str = f"{v.major}.{v.minor}.{v.micro}"
    if v >= (3, 12):
        return CheckResult("Python", "ok", version_str)
    return CheckResult(
        "Python",
        "fail",
        version_str,
        fix="Python 3.12+ required. Install from https://www.python.org/",
    )


def check_node() -> CheckResult:
    node = shutil.which("node")
    if not node:
        return CheckResult(
            "Node.js",
            "fail",
            fix="Install Node.js 22+: https://nodejs.org/",
        )
    out = _run(["node", "-v"]) or ""
    major = _parse_major(out)
    if major is None or major < 22:
        return CheckResult(
            "Node.js",
            "fail",
            out or "unknown version",
            fix="Node.js 22+ required. Install from https://nodejs.org/",
        )
    return CheckResult("Node.js", "ok", out.lstrip("v"))


def check_pnpm() -> CheckResult:
    try:
        result = subprocess.run(
            [sys.executable, str(PNPM_SCRIPT_PATH), "-v"],
            cwd=FRONTEND_DIR,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            shell=False,
        )
    except OSError as exc:
        return CheckResult(
            "pnpm",
            "fail",
            f"Unable to run pnpm resolver: {exc}",
            fix="Install pnpm, or install Corepack and ensure it is on PATH",
        )

    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()
    if result.returncode != 0:
        detail = "\n".join(part for part in (stderr, stdout) if part)
        return CheckResult(
            "pnpm",
            "fail",
            detail or f"pnpm resolver exited with status {result.returncode}",
            fix="Install pnpm, or install Corepack and ensure it is on PATH",
        )
    if not stdout:
        return CheckResult(
            "pnpm",
            "fail",
            stderr or "pnpm resolver returned no version",
            fix="Install pnpm, or install Corepack and ensure it is on PATH",
        )
    return CheckResult("pnpm", "ok", stdout)


def check_uv() -> CheckResult:
    if not shutil.which("uv"):
        return CheckResult(
            "uv",
            "fail",
            fix="curl -LsSf https://astral.sh/uv/install.sh | sh",
        )
    out = _run(["uv", "--version"]) or ""
    parts = out.split()
    version = parts[1] if len(parts) > 1 else out
    return CheckResult("uv", "ok", version)


def check_nginx() -> CheckResult:
    if shutil.which("nginx"):
        out = _run(["nginx", "-v"]) or ""
        version = out.split("/", 1)[-1] if "/" in out else out
        return CheckResult("nginx", "ok", version)
    return CheckResult(
        "nginx",
        "fail",
        fix=("macOS:   brew install nginx\nUbuntu:  sudo apt install nginx\nWindows: use WSL or Docker mode"),
    )


# Environment variables that choose which config file the Gateway loads.
CONFIG_LOCATION_ENV_VARS = ("DEER_FLOW_CONFIG_PATH", "DEER_FLOW_PROJECT_ROOT")


def _unquoted_dotenv_keys(env_path: Path) -> set[str]:
    """Return the ``.env`` keys whose value is written without quotes."""
    from dotenv.parser import parse_stream

    with open(env_path, encoding="utf-8") as stream:
        return {binding.key for binding in parse_stream(stream) if binding.key and binding.original.string.split("=", 1)[-1].lstrip()[:1] not in ("'", '"')}


def resolve_config_path() -> tuple[Path, CheckResult | None]:
    """Locate the config.yaml the Gateway would read.

    Delegates to the harness resolver (``DEER_FLOW_CONFIG_PATH``, then
    ``config.yaml`` under ``DEER_FLOW_PROJECT_ROOT``, then the legacy
    backend/repository-root locations) so doctor checks the same file the
    Gateway loads. When an environment override would stop the Gateway from
    starting, returns the path it names (which does not exist) and a failed
    ``config.yaml found`` result carrying the Gateway's error.
    """
    config_env = os.environ.get("DEER_FLOW_CONFIG_PATH")
    default_path = Path(os.environ.get("DEER_FLOW_PROJECT_ROOT") or ".") / "config.yaml"
    try:
        from deerflow.config.app_config import AppConfig
    except Exception as exc:
        # Keep diagnosing a broken backend environment instead of crashing
        # (any import-time failure, as in check_config_loadable); the
        # YAML-only checks still run against the most likely path.
        return Path(config_env) if config_env else default_path, CheckResult(
            "config.yaml found",
            "fail",
            f"cannot import the DeerFlow harness to resolve it ({type(exc).__name__}: {exc})",
            fix="Run 'make install'",
        )

    try:
        return AppConfig.resolve_config_path(), None
    except FileNotFoundError as exc:
        if not config_env:
            # Nothing at the default locations: a plain missing config.
            return default_path, None
        return Path(config_env), CheckResult(
            "config.yaml found",
            "fail",
            str(exc),
            fix="Point DEER_FLOW_CONFIG_PATH at an existing config.yaml, or unset it",
        )
    except ValueError as exc:
        return Path(os.environ["DEER_FLOW_PROJECT_ROOT"]) / "config.yaml", CheckResult(
            "config.yaml found",
            "fail",
            str(exc),
            fix="Point DEER_FLOW_PROJECT_ROOT at the DeerFlow checkout, or unset it",
        )


def check_config_exists(config_path: Path) -> CheckResult:
    if config_path.exists():
        return CheckResult("config.yaml found", "ok")
    return CheckResult(
        "config.yaml found",
        "fail",
        fix="Run 'make setup' to create it",
    )


def check_config_version(config_path: Path, project_root: Path) -> CheckResult:
    if not config_path.exists():
        return CheckResult("config.yaml version", "skip")

    try:
        import yaml

        with open(config_path, encoding="utf-8") as f:
            user_data = yaml.safe_load(f) or {}
        user_ver = int(user_data.get("config_version", 0))
    except Exception as exc:
        return CheckResult("config.yaml version", "fail", str(exc))

    example_path = project_root / "config.example.yaml"
    if not example_path.exists():
        return CheckResult("config.yaml version", "skip", "config.example.yaml not found")

    try:
        import yaml

        with open(example_path, encoding="utf-8") as f:
            example_data = yaml.safe_load(f) or {}
        example_ver = int(example_data.get("config_version", 0))
    except Exception:
        return CheckResult("config.yaml version", "skip")

    if user_ver < example_ver:
        return CheckResult(
            "config.yaml version",
            "warn",
            f"v{user_ver} < v{example_ver} (latest)",
            fix="make config-upgrade",
        )
    return CheckResult("config.yaml version", "ok", f"v{user_ver}")


def check_models_configured(config_path: Path) -> CheckResult:
    if not config_path.exists():
        return CheckResult("models configured", "skip")
    try:
        data = _load_yaml_file(config_path)
        models = data.get("models") or []
        if models:
            return CheckResult("models configured", "ok", f"{len(models)} model(s)")
        return CheckResult(
            "models configured",
            "fail",
            "no models found",
            fix="Run 'make setup' to configure an LLM provider",
        )
    except Exception as exc:
        return CheckResult("models configured", "fail", str(exc))


def check_config_loadable(config_path: Path) -> CheckResult:
    if not config_path.exists():
        return CheckResult("config.yaml loadable", "skip")

    try:
        _load_app_config(config_path)
        return CheckResult("config.yaml loadable", "ok")
    except Exception as exc:
        return CheckResult(
            "config.yaml loadable",
            "fail",
            str(exc),
            fix="Run 'make setup' again, or compare with config.example.yaml",
        )


def check_llm_api_key(config_path: Path) -> list[CheckResult]:
    """Check that each model's env var is set in the environment."""
    if not config_path.exists():
        return []

    results: list[CheckResult] = []
    try:
        import yaml
        from dotenv import load_dotenv

        env_path = config_path.parent / ".env"
        if env_path.exists():
            load_dotenv(env_path, override=False)

        with open(config_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        for model in data.get("models") or []:
            # Collect all values that look like $ENV_VAR references
            def _collect_env_refs(obj: object) -> list[str]:
                refs: list[str] = []
                if isinstance(obj, str) and obj.startswith("$"):
                    refs.append(obj[1:])
                elif isinstance(obj, dict):
                    for v in obj.values():
                        refs.extend(_collect_env_refs(v))
                elif isinstance(obj, list):
                    for item in obj:
                        refs.extend(_collect_env_refs(item))
                return refs

            env_refs = _collect_env_refs(model)
            model_name = model.get("name", "default")
            for var in env_refs:
                label = f"{var} set (model: {model_name})"
                if os.environ.get(var):
                    results.append(CheckResult(label, "ok"))
                else:
                    results.append(
                        CheckResult(
                            label,
                            "fail",
                            fix=f"Add {var}=<your-key> to your .env file",
                        )
                    )
    except Exception as exc:
        results.append(CheckResult("LLM API key check", "fail", str(exc)))

    return results


def check_llm_package(config_path: Path) -> list[CheckResult]:
    """Check that the LangChain provider package is installed."""
    if not config_path.exists():
        return []

    results: list[CheckResult] = []
    try:
        import yaml

        with open(config_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        seen_packages: set[str] = set()
        for model in data.get("models") or []:
            use = model.get("use", "")
            if ":" in use:
                package_path = use.split(":")[0]
                # e.g. langchain_openai → langchain-openai
                top_level = package_path.split(".")[0]
                pip_name = top_level.replace("_", "-")
                if pip_name in seen_packages:
                    continue
                seen_packages.add(pip_name)
                label = f"{pip_name} installed"
                try:
                    __import__(top_level)
                    results.append(CheckResult(label, "ok"))
                except ImportError:
                    results.append(
                        CheckResult(
                            label,
                            "fail",
                            fix=f"cd backend && uv add {pip_name}",
                        )
                    )
    except Exception as exc:
        results.append(CheckResult("LLM package check", "fail", str(exc)))

    return results


def check_llm_auth(config_path: Path) -> list[CheckResult]:
    if not config_path.exists():
        return []

    results: list[CheckResult] = []
    try:
        data = _load_yaml_file(config_path)
        for model in data.get("models") or []:
            use = model.get("use", "")
            model_name = model.get("name", "default")

            if use == "deerflow.models.openai_codex_provider:CodexChatModel":
                auth_path = Path(os.environ.get("CODEX_AUTH_PATH", "~/.codex/auth.json")).expanduser()
                if _codex_auth_file_has_access_token(auth_path):
                    results.append(CheckResult(f"Codex CLI auth available (model: {model_name})", "ok", str(auth_path)))
                else:
                    results.append(
                        CheckResult(
                            f"Codex CLI auth available (model: {model_name})",
                            "fail",
                            str(auth_path),
                            fix="Run `codex login`, or set CODEX_AUTH_PATH to an auth.json containing a valid access token",
                        )
                    )

            if use == "deerflow.models.claude_provider:ClaudeChatModel":
                credential_paths = [Path(os.environ["CLAUDE_CODE_CREDENTIALS_PATH"]).expanduser() for env_name in ("CLAUDE_CODE_CREDENTIALS_PATH",) if os.environ.get(env_name)]
                credential_paths.append(Path("~/.claude/.credentials.json").expanduser())
                has_oauth_env = any(
                    (os.environ.get(name) or "").strip()
                    for name in (
                        "ANTHROPIC_API_KEY",
                        "CLAUDE_CODE_OAUTH_TOKEN",
                        "ANTHROPIC_AUTH_TOKEN",
                        "CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR",
                    )
                )
                existing_path = next((path for path in credential_paths if path.exists()), None)
                valid_path = next((path for path in credential_paths if _claude_credentials_file_has_access_token(path)), None)
                if has_oauth_env or valid_path is not None:
                    detail = "env var set" if has_oauth_env else str(valid_path)
                    results.append(CheckResult(f"Claude auth available (model: {model_name})", "ok", detail))
                else:
                    results.append(
                        CheckResult(
                            f"Claude auth available (model: {model_name})",
                            "fail",
                            str(existing_path) if existing_path is not None else "",
                            fix=("Set ANTHROPIC_API_KEY / CLAUDE_CODE_OAUTH_TOKEN, or place credentials at ~/.claude/.credentials.json"),
                        )
                    )
    except Exception as exc:
        results.append(CheckResult("LLM auth check", "fail", str(exc)))
    return results


def check_web_search(config_path: Path) -> CheckResult:
    return check_web_tool(config_path, tool_name="web_search", label="web search configured")


def check_web_tool(config_path: Path, *, tool_name: str, label: str) -> CheckResult:
    """Warn (not fail) if a web capability is not configured."""
    if not config_path.exists():
        return CheckResult(label, "skip")

    try:
        from dotenv import load_dotenv

        env_path = config_path.parent / ".env"
        if env_path.exists():
            load_dotenv(env_path, override=False)

        data = _load_yaml_file(config_path)

        tool_entries = [t for t in (data.get("tools") or []) if isinstance(t, dict) and t.get("name") == tool_name]
        if not tool_entries:
            return CheckResult(
                label,
                "warn",
                f"no {tool_name} tool in config",
                fix=f"Run 'make setup' to configure {tool_name}",
            )

        free_providers = {
            "web_search": {
                "ddg_search": "DuckDuckGo (no key needed)",
                "youcom": "You.com (works with no key; YDC_API_KEY enables the full Search API)",
            },
            "web_fetch": {"jina_ai": "Jina AI Reader (no key needed)", "crawl4ai": "Crawl4AI (self-hosted, no key needed)"},
            "image_search": {"deerflow.community.image_search.tools": "DuckDuckGo Images (no key needed)"},
        }
        key_providers = {
            "web_search": {
                "tavily": "TAVILY_API_KEY",
                "infoquest": "INFOQUEST_API_KEY",
                "exa": "EXA_API_KEY",
                "firecrawl": "FIRECRAWL_API_KEY",
                "fastcrw": "CRW_API_KEY",
                "brave": "BRAVE_SEARCH_API_KEY",
                "serper": "SERPER_API_KEY",
                "serply": "SERPLY_API_KEY",
                "sofya": "SOFYA_API_KEY",
                "tencent_wsa": "TENCENTCLOUD_WSA_APIKEY",
                "webz": "WEBZ_API_KEY",
            },
            "web_fetch": {
                "infoquest": "INFOQUEST_API_KEY",
                "exa": "EXA_API_KEY",
                "firecrawl": "FIRECRAWL_API_KEY",
                "fastcrw": "CRW_API_KEY",
                "sofya": "SOFYA_API_KEY",
                "unbrowse": "UNBROWSE_API_KEY",
            },
            "image_search": {
                "brave": "BRAVE_SEARCH_API_KEY",
                "infoquest": "INFOQUEST_API_KEY",
                "serper": "SERPER_API_KEY",
            },
            "web_capture": {
                "browserless": "BROWSERLESS_TOKEN",
            },
        }
        key_fields = {
            "web_capture": {
                "browserless": "token",
            },
        }

        def _configured_key_detail(tool: dict, default_var: str, key_field: str = "api_key") -> tuple[Status, str] | None:
            configured_key = tool.get(key_field)
            if isinstance(configured_key, str) and configured_key.strip():
                key = configured_key.strip()
                if key.startswith("$"):
                    env_name = key[1:]
                    val = os.environ.get(env_name)
                    if val and val.strip():
                        return ("ok", f"{env_name} set from config")
                    # The referenced var is unset; fall through to the default
                    # env var below, which tools use as a runtime fallback.
                else:
                    return ("warn", f"literal {key_field} set in config")

            val = os.environ.get(default_var)
            return ("ok", f"{default_var} set") if val and val.strip() else None

        def _browserless_self_hosted(tool: dict) -> bool:
            base_url = str(tool.get("base_url") or "http://localhost:3032").lower()
            return "browserless.io" not in base_url

        def _delegated_backend_error(tool: dict) -> tuple[str, str] | None:
            if tool_name not in {"web_fetch", "web_capture"}:
                return None
            providers = {
                "browserless": ("Browserless", "http://localhost:3032"),
                "crawl4ai": ("Crawl4AI", "http://localhost:11235"),
                "firecrawl": ("Firecrawl", None),
                "fastcrw": ("fastCRW", "https://fastcrw.com/api"),
            }
            use = str(tool.get("use") or "")
            for provider, (provider_label, default_url) in providers.items():
                if not use.startswith(f"deerflow.community.{provider}."):
                    continue
                if tool_name == "web_capture" and provider != "browserless":
                    return None

                from deerflow.community.url_safety import validate_delegated_backend_url
                from deerflow.config.app_config import AppConfig

                # Resolve only backend settings: credential diagnostics below
                # still need the literal values and environment references.
                cfg = AppConfig.resolve_env_variables({key: tool[key] for key in ("base_url", "network_isolation_confirmed") if key in tool})
                base_url = cfg.get("base_url", default_url)
                if provider == "fastcrw" and cfg.get("base_url") is None:
                    base_url = os.environ.get("CRW_API_URL", default_url)
                if provider == "firecrawl" and base_url is None:
                    # The SDK uses its public cloud endpoint when unset.
                    return None
                confirmed = cfg.get("network_isolation_confirmed")
                confirmed = confirmed if isinstance(confirmed, bool) else isinstance(confirmed, str) and confirmed.strip().lower() in {"1", "true", "yes", "on"}
                error = validate_delegated_backend_url(base_url, network_isolation_confirmed=confirmed)
                return (provider_label, error) if error else None
            return None

        # Check every delegated backend before any provider's early success.
        # allow_private_addresses permits targets, not backend delegation.
        for tool in tool_entries:
            backend_error = _delegated_backend_error(tool)
            if backend_error:
                provider, error = backend_error
                return CheckResult(
                    label,
                    "warn",
                    f"{provider} backend: {error}",
                    fix="Configure an HTTP(S) backend URL; for a private or unverifiable backend, isolate its egress before setting network_isolation_confirmed: true. See backend/docs/CONFIGURATION.md#delegated-fetch-backend-isolation",
                )

        for tool in tool_entries:
            use = tool.get("use", "")
            for provider, detail in free_providers.get(tool_name, {}).items():
                if provider in use:
                    return CheckResult(label, "ok", detail)

        for tool in tool_entries:
            use = tool.get("use", "")
            for provider, var in key_providers.get(tool_name, {}).items():
                if provider in use:
                    key_field = key_fields.get(tool_name, {}).get(provider, "api_key")
                    key_status = _configured_key_detail(tool, var, key_field=key_field)
                    if key_status:
                        status, detail = key_status
                        if status == "warn":
                            return CheckResult(
                                label,
                                "warn",
                                f"{provider} ({detail})",
                                fix=f"Move the {key_field} to .env as {var}=<your-key> and reference it as ${var}",
                            )
                        return CheckResult(label, "ok", f"{provider} ({detail})")
                    if tool_name == "web_capture" and provider == "browserless" and _browserless_self_hosted(tool):
                        return CheckResult(label, "ok", "browserless (self-hosted, token optional)")
                    return CheckResult(
                        label,
                        "warn",
                        f"{provider} configured but {var} not set",
                        fix=f"Add {var}=<your-key> to .env, or run 'make setup'",
                    )

        for tool in tool_entries:
            use = tool.get("use", "")
            split = _split_use_path(use)
            if split is None:
                return CheckResult(
                    label,
                    "fail",
                    f"invalid use path: {use}",
                    fix="Use a valid module:path provider from config.example.yaml",
                )
            module_name, attr_name = split
            try:
                module = import_module(module_name)
                getattr(module, attr_name)
            except Exception as exc:
                return CheckResult(
                    label,
                    "fail",
                    f"provider import failed: {use} ({exc})",
                    fix="Install the provider dependency or pick a valid provider in `make setup`",
                )

        return CheckResult(label, "ok")
    except Exception as exc:
        return CheckResult(label, "warn", str(exc))


def check_web_fetch(config_path: Path) -> CheckResult:
    return check_web_tool(config_path, tool_name="web_fetch", label="web fetch configured")


def check_web_capture(config_path: Path) -> CheckResult:
    return check_web_tool(config_path, tool_name="web_capture", label="web capture configured")


def check_image_search(config_path: Path) -> CheckResult:
    return check_web_tool(config_path, tool_name="image_search", label="image search configured")


def check_frontend_env(project_root: Path) -> CheckResult:
    env_path = project_root / "frontend" / ".env"
    if env_path.exists():
        return CheckResult("frontend/.env found", "ok")
    return CheckResult(
        "frontend/.env found",
        "warn",
        fix="Run 'make setup' or copy frontend/.env.example to frontend/.env",
    )


def check_sandbox(config_path: Path) -> list[CheckResult]:
    if not config_path.exists():
        return [CheckResult("sandbox configured", "skip")]

    try:
        data = _load_yaml_file(config_path)
        sandbox = data.get("sandbox")
        if not isinstance(sandbox, dict):
            return [
                CheckResult(
                    "sandbox configured",
                    "fail",
                    "missing sandbox section",
                    fix="Run 'make setup' to choose an execution mode",
                )
            ]

        sandbox_use = sandbox.get("use", "")
        tools = data.get("tools") or []
        tool_names = {tool.get("name") for tool in tools if isinstance(tool, dict)}
        results: list[CheckResult] = []

        if "LocalSandboxProvider" in sandbox_use:
            results.append(CheckResult("sandbox configured", "ok", "Local sandbox"))
            has_bash_tool = "bash" in tool_names
            allow_host_bash = bool(sandbox.get("allow_host_bash", False))
            if has_bash_tool and not allow_host_bash:
                results.append(
                    CheckResult(
                        "bash compatibility",
                        "warn",
                        "bash tool configured but host bash is disabled",
                        fix="Enable host bash only in a fully trusted environment, or switch to container sandbox",
                    )
                )
            elif allow_host_bash:
                results.append(
                    CheckResult(
                        "bash compatibility",
                        "warn",
                        "host bash enabled on LocalSandboxProvider",
                        fix="Use container sandbox for stronger isolation when bash is required",
                    )
                )
        elif "AioSandboxProvider" in sandbox_use:
            results.append(CheckResult("sandbox configured", "ok", "Container sandbox"))
            if not sandbox.get("provisioner_url") and not (shutil.which("docker") or shutil.which("container")):
                results.append(
                    CheckResult(
                        "container runtime available",
                        "warn",
                        "no Docker/Apple Container runtime detected",
                        fix="Install Docker Desktop / Apple Container, or switch to local sandbox",
                    )
                )
        elif sandbox_use:
            results.append(CheckResult("sandbox configured", "ok", sandbox_use))
        else:
            results.append(
                CheckResult(
                    "sandbox configured",
                    "fail",
                    "sandbox.use is empty",
                    fix="Run 'make setup' to choose an execution mode",
                )
            )
        return results
    except Exception as exc:
        return [CheckResult("sandbox configured", "fail", str(exc))]


def check_env_file(project_root: Path) -> CheckResult:
    env_path = project_root / ".env"
    if env_path.exists():
        return CheckResult(".env found", "ok")
    return CheckResult(
        ".env found",
        "warn",
        fix="Run 'make setup' or copy .env.example to .env",
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]

    # Load .env early so key checks work
    try:
        from dotenv import dotenv_values, load_dotenv

        env_path = project_root / ".env"
        if env_path.exists():
            load_dotenv(env_path, override=False)
            # `make dev` (scripts/serve.sh) sources .env over the shell, so
            # for the variables that choose the config file, .env wins.
            unquoted = _unquoted_dotenv_keys(env_path)
            for name, value in dotenv_values(env_path).items():
                if name in CONFIG_LOCATION_ENV_VARS and value is not None:
                    # `source` expands an unquoted leading `~`, not a quoted one.
                    os.environ[name] = os.path.expanduser(value) if name in unquoted else value
    except ImportError:
        pass

    # serve.sh then replaces an unset or empty runtime root with the
    # checkout, so config resolution and the loadable check see what the
    # Gateway sees.
    if not os.environ.get("DEER_FLOW_PROJECT_ROOT"):
        os.environ["DEER_FLOW_PROJECT_ROOT"] = str(project_root)
    config_path, config_failure = resolve_config_path()

    print()
    print(bold("DeerFlow Health Check"))
    print("═" * 40)

    sections: list[tuple[str, list[CheckResult]]] = []

    # ── System Requirements ────────────────────────────────────────────────────
    sys_checks = [
        check_python(),
        check_node(),
        check_pnpm(),
        check_uv(),
        check_nginx(),
    ]
    sections.append(("System Requirements", sys_checks))

    # ── Configuration ─────────────────────────────────────────────────────────
    cfg_checks: list[CheckResult] = [
        check_env_file(project_root),
        check_frontend_env(project_root),
        config_failure or check_config_exists(config_path),
        check_config_version(config_path, project_root),
        check_config_loadable(config_path),
        check_models_configured(config_path),
    ]
    sections.append(("Configuration", cfg_checks))

    # ── LLM Provider ──────────────────────────────────────────────────────────
    llm_checks: list[CheckResult] = [
        *check_llm_api_key(config_path),
        *check_llm_auth(config_path),
        *check_llm_package(config_path),
    ]
    sections.append(("LLM Provider", llm_checks))

    # ── Web Capabilities ─────────────────────────────────────────────────────
    search_checks = [
        check_web_search(config_path),
        check_web_fetch(config_path),
        check_web_capture(config_path),
        check_image_search(config_path),
    ]
    sections.append(("Web Capabilities", search_checks))

    # ── Sandbox ──────────────────────────────────────────────────────────────
    sandbox_checks = check_sandbox(config_path)
    sections.append(("Sandbox", sandbox_checks))

    # ── Render ────────────────────────────────────────────────────────────────
    total_fails = 0
    total_warns = 0

    for section_title, checks in sections:
        print()
        print(bold(section_title))
        for cr in checks:
            cr.print()
            if cr.status == "fail":
                total_fails += 1
            elif cr.status == "warn":
                total_warns += 1

    # ── Summary ───────────────────────────────────────────────────────────────
    print()
    print("═" * 40)
    if total_fails == 0 and total_warns == 0:
        print(f"Status: {green('Ready')}")
        print(f"Run {cyan('make dev')} to start DeerFlow")
    elif total_fails == 0:
        print(f"Status: {yellow(f'Ready ({total_warns} warning(s))')}")
        print(f"Run {cyan('make dev')} to start DeerFlow")
    else:
        print(f"Status: {red(f'{total_fails} error(s), {total_warns} warning(s)')}")
        print("Fix the errors above, then run 'make doctor' again.")

    print()
    return 0 if total_fails == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
