#!/usr/bin/env python3
"""DeerFlow Health Check (make doctor).

Checks system requirements, configuration, LLM provider, and optional
components, then prints an actionable report.

Exit codes:
  0 — all required checks passed (warnings allowed)
  1 — one or more required checks failed
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from importlib import import_module
from pathlib import Path
from typing import Literal

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

Status = Literal["ok", "warn", "fail", "skip"]


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
        r = subprocess.run(cmd, capture_output=True, text=True, check=True)
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
    candidates = [["pnpm"], ["pnpm.cmd"]]
    if shutil.which("corepack"):
        candidates.append(["corepack", "pnpm"])
    for cmd in candidates:
        if shutil.which(cmd[0]):
            out = _run([*cmd, "-v"]) or ""
            return CheckResult("pnpm", "ok", out)
    return CheckResult(
        "pnpm",
        "fail",
        fix="npm install -g pnpm   (or: corepack enable)",
    )


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
        fix=(
            "macOS:   brew install nginx\n"
            "Ubuntu:  sudo apt install nginx\n"
            "Windows: use WSL or Docker mode"
        ),
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
        models = data.get("models", [])
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

        for model in data.get("models", []):
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
        for model in data.get("models", []):
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
        for model in data.get("models", []):
            use = model.get("use", "")
            model_name = model.get("name", "default")

            if use == "deerflow.models.openai_codex_provider:CodexChatModel":
                auth_path = Path(os.environ.get("CODEX_AUTH_PATH", "~/.codex/auth.json")).expanduser()
                if auth_path.exists():
                    results.append(CheckResult(f"Codex CLI auth available (model: {model_name})", "ok", str(auth_path)))
                else:
                    results.append(
                        CheckResult(
                            f"Codex CLI auth available (model: {model_name})",
                            "fail",
                            str(auth_path),
                            fix="Run `codex login`, or set CODEX_AUTH_PATH to a valid auth.json",
                        )
                    )

            if use == "deerflow.models.claude_provider:ClaudeChatModel":
                credential_paths = [
                    Path(os.environ["CLAUDE_CODE_CREDENTIALS_PATH"]).expanduser()
                    for env_name in ("CLAUDE_CODE_CREDENTIALS_PATH",)
                    if os.environ.get(env_name)
                ]
                credential_paths.append(Path("~/.claude/.credentials.json").expanduser())
                has_oauth_env = any(
                    os.environ.get(name)
                    for name in (
                        "ANTHROPIC_API_KEY",
                        "CLAUDE_CODE_OAUTH_TOKEN",
                        "ANTHROPIC_AUTH_TOKEN",
                        "CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR",
                    )
                )
                existing_path = next((path for path in credential_paths if path.exists()), None)
                if has_oauth_env or existing_path is not None:
                    detail = "env var set" if has_oauth_env else str(existing_path)
                    results.append(CheckResult(f"Claude auth available (model: {model_name})", "ok", detail))
                else:
                    results.append(
                        CheckResult(
                            f"Claude auth available (model: {model_name})",
                            "fail",
                            fix=(
                                "Set ANTHROPIC_API_KEY / CLAUDE_CODE_OAUTH_TOKEN, "
                                "or place credentials at ~/.claude/.credentials.json"
                            ),
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

        tool_uses = [t.get("use", "") for t in data.get("tools", []) if t.get("name") == tool_name]
        if not tool_uses:
            return CheckResult(
                label,
                "warn",
                f"no {tool_name} tool in config",
                fix=f"Run 'make setup' to configure {tool_name}",
            )

        free_providers = {
            "web_search": {"ddg_search": "DuckDuckGo (no key needed)"},
            "web_fetch": {"jina_ai": "Jina AI Reader (no key needed)"},
        }
        key_providers = {
            "web_search": {
                "tavily": "TAVILY_API_KEY",
                "infoquest": "INFOQUEST_API_KEY",
                "exa": "EXA_API_KEY",
                "firecrawl": "FIRECRAWL_API_KEY",
            },
            "web_fetch": {
                "infoquest": "INFOQUEST_API_KEY",
                "exa": "EXA_API_KEY",
                "firecrawl": "FIRECRAWL_API_KEY",
            },
        }

        for use in tool_uses:
            for provider, detail in free_providers.get(tool_name, {}).items():
                if provider in use:
                    return CheckResult(label, "ok", detail)

        for use in tool_uses:
            for provider, var in key_providers.get(tool_name, {}).items():
                if provider in use:
                    val = os.environ.get(var)
                    if val:
                        return CheckResult(label, "ok", f"{provider} ({var} set)")
                    return CheckResult(
                        label,
                        "warn",
                        f"{provider} configured but {var} not set",
                        fix=f"Add {var}=<your-key> to .env, or run 'make setup'",
                    )

        for use in tool_uses:
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
        tools = data.get("tools", [])
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
    config_path = project_root / "config.yaml"

    # Load .env early so key checks work
    try:
        from dotenv import load_dotenv

        env_path = project_root / ".env"
        if env_path.exists():
            load_dotenv(env_path, override=False)
    except ImportError:
        pass

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
        check_config_exists(config_path),
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
    search_checks = [check_web_search(config_path), check_web_fetch(config_path)]
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
