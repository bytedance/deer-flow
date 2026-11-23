"""Docker Compose deployment contract tests (workers, writable mounts, proxy trust, credentials key, and nginx guards)."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml
from _gateway_shutdown_budget import HOOKS_BOUNDED_BY_SHUTDOWN_HOOK_TIMEOUT, lifespan_shutdown_seconds
from support.compose import DOCKER, requires_docker_compose
from support.nginx_conf import NGINX_CONFIGS, read_config
from support.shell import find_script_bash

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_PATHS = {
    "prod": REPO_ROOT / "docker" / "docker-compose.yaml",
    "dev": REPO_ROOT / "docker" / "docker-compose-dev.yaml",
}
BASH_EXECUTABLE = find_script_bash()


def _render_gateway_env_through_docker_start(
    tmp_path: Path,
    env_file: str,
    shell_value: str | None = None,
    *,
    shell_var: str,
) -> dict[str, str]:
    """Render the dev gateway environment with the exact command, cwd, and environment ``make docker-start`` uses."""
    docker_dir = tmp_path / "docker"
    shutil.copytree(REPO_ROOT / "docker", docker_dir)
    (tmp_path / "frontend").mkdir()
    (tmp_path / "frontend" / ".env").write_text("", encoding="utf-8")
    (tmp_path / ".env").write_text(env_file, encoding="utf-8")
    (tmp_path / "config.yaml").write_text(
        "sandbox:\n  use: deerflow.sandbox.local:LocalSandboxProvider\n",
        encoding="utf-8",
    )
    (tmp_path / "extensions_config.json").write_text("{}", encoding="utf-8")
    rendered = tmp_path / "rendered.json"
    env = {key: value for key, value in os.environ.items() if not key.startswith(("DEER_FLOW_", "COMPOSE_", "AUTH_"))}
    if shell_value is not None:
        env[shell_var] = shell_value
    script = f"""
source '{REPO_ROOT / "scripts" / "docker.sh"}'
PROJECT_ROOT='{tmp_path}'
DOCKER_DIR='{docker_dir}'
require_compose_version() {{ :; }}
docker() {{
    local args=()
    for arg in "$@"; do
        [ "$arg" = up ] && break
        args+=("$arg")
    done
    command '{DOCKER}' "${{args[@]}}" config --format json > '{rendered}'
}}
start
"""
    subprocess.run([BASH_EXECUTABLE, "-c", script], env=env, capture_output=True, text=True, timeout=120, check=True)
    return json.loads(rendered.read_text(encoding="utf-8"))["services"]["gateway"]["environment"]


def _render_trusted_proxies_through_docker_start(
    tmp_path: Path,
    env_file: str,
    shell_value: str | None = None,
) -> dict[str, str]:
    return _render_gateway_env_through_docker_start(
        tmp_path,
        env_file,
        shell_value,
        shell_var="AUTH_TRUSTED_PROXIES",
    )


def _render_credentials_key_through_docker_start(
    tmp_path: Path,
    env_file: str,
    shell_value: str | None,
) -> dict[str, str]:
    return _render_gateway_env_through_docker_start(
        tmp_path,
        env_file,
        shell_value,
        shell_var="DEER_FLOW_CREDENTIALS_KEY",
    )


# --- test_compose_auth_trusted_proxies ---

EXPECTED_TRUSTED_PROXIES_ENTRY = "AUTH_TRUSTED_PROXIES=${AUTH_TRUSTED_PROXIES:-nginx}"


@pytest.mark.parametrize("variant", sorted(COMPOSE_PATHS))
def test_gateway_trusts_the_bundled_nginx_service_by_default(variant: str):
    compose = yaml.safe_load(COMPOSE_PATHS[variant].read_text(encoding="utf-8"))
    services = compose["services"]

    assert EXPECTED_TRUSTED_PROXIES_ENTRY in services["gateway"]["environment"]
    # The default resolves only while the proxy is the service named ``nginx``
    # on a network the Gateway shares.
    assert set(services["nginx"]["networks"]) & set(services["gateway"]["networks"])


def _render(tmp_path: Path, variant: str, env_file: str | None) -> dict:
    """Render the compose file the way deploy.sh calls it (``--env-file ../.env``)."""
    docker_dir = tmp_path / "docker"
    shutil.copytree(REPO_ROOT / "docker", docker_dir)
    (tmp_path / "frontend").mkdir(exist_ok=True)
    env = {key: value for key, value in os.environ.items() if not key.startswith(("DEER_FLOW_", "COMPOSE_", "AUTH_"))}
    env.update(
        DEER_FLOW_ROOT=str(tmp_path),
        DEER_FLOW_HOME=str(tmp_path / "home"),
        DEER_FLOW_REPO_ROOT=str(tmp_path),
        DEER_FLOW_CONFIG_PATH=str(tmp_path / "config.yaml"),
        DEER_FLOW_EXTENSIONS_CONFIG_PATH=str(tmp_path / "extensions_config.json"),
        BETTER_AUTH_SECRET="test-secret",
        DEER_FLOW_INTERNAL_AUTH_TOKEN="test-token",
    )
    command = [DOCKER, "compose"]
    if env_file is not None:
        (tmp_path / ".env").write_text(env_file, encoding="utf-8")
        command += ["--env-file", str(tmp_path / ".env")]
    command += ["-p", "deer-flow-trusted-proxies-test", "-f", str(docker_dir / COMPOSE_PATHS[variant].name), "config", "--format", "json"]
    result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=120, check=False)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)["services"]["gateway"]["environment"]


@requires_docker_compose
@pytest.mark.parametrize("variant", sorted(COMPOSE_PATHS))
@pytest.mark.parametrize(
    ("env_file", "expected"),
    [(None, "nginx"), ("AUTH_TRUSTED_PROXIES=\n", "nginx"), ("AUTH_TRUSTED_PROXIES=10.0.0.0/8,edge-proxy\n", "10.0.0.0/8,edge-proxy")],
    # An explicitly empty value is not direct mode here: every browser request
    # comes through nginx, so it would only bring back the shared lockout.
    ids=["default", "explicitly-empty", "operator-override"],
)
def test_real_compose_renders_the_default_and_keeps_an_operator_override(tmp_path, variant: str, env_file: str | None, expected: str):
    assert _render(tmp_path, variant, env_file)["AUTH_TRUSTED_PROXIES"] == expected


@requires_docker_compose
@pytest.mark.skipif(BASH_EXECUTABLE is None, reason="bash is required to run scripts/docker.sh")
@pytest.mark.parametrize(
    ("env_file", "shell_value", "expected"),
    [
        ("", None, "nginx"),
        ("AUTH_TRUSTED_PROXIES=\n", None, "nginx"),
        ("AUTH_TRUSTED_PROXIES=10.0.0.0/8,edge-proxy\n", None, "10.0.0.0/8,edge-proxy"),
        ("AUTH_TRUSTED_PROXIES='10.0.0.0/8'\r\n", None, "10.0.0.0/8"),
        ("AUTH_TRUSTED_PROXIES=10.0.0.0/8\n", "192.0.2.1", "192.0.2.1"),
    ],
    ids=["default", "explicitly-empty", "dotenv-override", "quoted-crlf", "shell-export-wins"],
)
def test_make_docker_start_keeps_a_dotenv_override(tmp_path, env_file: str, shell_value: str | None, expected: str):
    """The dev launcher must hand the checkout .env value to interpolation, or the default replaces it."""
    assert _render_trusted_proxies_through_docker_start(tmp_path, env_file, shell_value)["AUTH_TRUSTED_PROXIES"] == expected


def _gateway_locations(content: str) -> list[tuple[str, str]]:
    """``(selector, block)`` for every location whose ``proxy_pass`` targets the Gateway."""
    locations = []
    for match in re.finditer(r"^\s*location\s+([^{#\n]+?)\s*\{", content, re.MULTILINE):
        start = match.end() - 1
        depth = 0
        for index in range(start, len(content)):
            if content[index] == "{":
                depth += 1
            elif content[index] == "}":
                depth -= 1
                if depth == 0:
                    block = content[start : index + 1]
                    break
        proxy_pass = re.search(r"proxy_pass\s+([^;]+);", block)
        if proxy_pass and "gateway" in proxy_pass.group(1):
            locations.append((match.group(1), block))
    return locations


@pytest.mark.parametrize("path", NGINX_CONFIGS)
def test_every_gateway_location_overwrites_x_real_ip(path: str):
    """A location that forwarded the client's own X-Real-IP would let anyone pick their lockout bucket."""
    locations = _gateway_locations(read_config(path))

    assert len(locations) >= 10, f"{path}: found only {len(locations)} gateway locations; did the parser break?"
    missing = [selector for selector, block in locations if not re.search(r"proxy_set_header\s+X-Real-IP\s+\$remote_addr\s*;", block)]
    assert missing == [], f"{path}: gateway locations that pass the client's X-Real-IP through: {missing}"


# --- test_compose_credentials_key ---

EXPECTED_CREDENTIALS_KEY_ENTRY = "DEER_FLOW_CREDENTIALS_KEY=${DEER_FLOW_CREDENTIALS_KEY:-}"


DOTENV_KEY = "u6Tp1Gk0bq8m6C2YkS9oWw7xH3fLr5eN1aZdQjVtXc4="


SHELL_KEY = "Zq3Lw8Rn2Tb6Yv1Kc5Hm9Pd4Sx7Ga0Je3Uf6Ni2Ro8M="


@pytest.mark.parametrize("variant", sorted(COMPOSE_PATHS))
def test_gateway_receives_the_credentials_key(variant: str) -> None:
    services = yaml.safe_load(COMPOSE_PATHS[variant].read_text(encoding="utf-8"))["services"]

    assert EXPECTED_CREDENTIALS_KEY_ENTRY in services["gateway"]["environment"]
    assert "DEER_FLOW_HOME=/app/backend/.deer-flow" in services["gateway"]["environment"], "the fallback key file lives in the runtime home"


@pytest.mark.parametrize("variant", sorted(COMPOSE_PATHS))
def test_only_the_gateway_receives_the_credentials_key(variant: str) -> None:
    services = yaml.safe_load(COMPOSE_PATHS[variant].read_text(encoding="utf-8"))["services"]
    for name, service in services.items():
        if name == "gateway":
            continue
        environment = service.get("environment") or []
        entries = environment if isinstance(environment, list) else [f"{key}={value}" for key, value in environment.items()]
        assert not any(str(entry).startswith("DEER_FLOW_CREDENTIALS_KEY") for entry in entries), name


@requires_docker_compose
@pytest.mark.skipif(BASH_EXECUTABLE is None, reason="bash is required to run scripts/docker.sh")
@pytest.mark.parametrize(
    ("env_file", "shell_value", "expected"),
    [
        ("", None, ""),
        (f"DEER_FLOW_CREDENTIALS_KEY={DOTENV_KEY}\n", None, DOTENV_KEY),
        (f"DEER_FLOW_CREDENTIALS_KEY='{DOTENV_KEY}'\r\n", None, DOTENV_KEY),
        (f"DEER_FLOW_CREDENTIALS_KEY={DOTENV_KEY}\n", SHELL_KEY, SHELL_KEY),
    ],
    ids=["unset", "dotenv", "quoted-crlf", "shell-export-wins"],
)
def test_make_docker_start_keeps_the_dotenv_credentials_key(tmp_path, env_file: str, shell_value: str | None, expected: str):
    """The dev launcher must hand the checkout .env key to interpolation; an empty override would replace it."""
    assert _render_credentials_key_through_docker_start(tmp_path, env_file, shell_value)["DEER_FLOW_CREDENTIALS_KEY"] == expected


# --- test_compose_default_workers ---

COMPOSE_PATH = REPO_ROOT / "docker" / "docker-compose.yaml"


DEV_COMPOSE_PATH = REPO_ROOT / "docker" / "docker-compose-dev.yaml"


DEV_ENTRYPOINT_PATH = REPO_ROOT / "docker" / "dev-entrypoint.sh"


GATEWAY_APP_PATH = REPO_ROOT / "backend" / "app" / "gateway" / "app.py"


def _gateway_command() -> str:
    """Return the gateway service command as a single string."""
    compose = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
    command = compose["services"]["gateway"]["command"]
    # ``command`` may load as a scalar string or a list depending on YAML style.
    if isinstance(command, list):
        command = " ".join(str(part) for part in command)
    return command


def test_gateway_defaults_to_single_worker():
    """With GATEWAY_WORKERS unset, the worker count must default to 1."""
    command = _gateway_command()
    match = re.search(r"GATEWAY_WORKERS:-(\d+)", command)
    assert match is not None, f"gateway command must set a GATEWAY_WORKERS default; got: {command}"
    assert match.group(1) == "1", f"default Gateway worker count must be 1, got {match.group(1)}"


def test_gateway_worker_count_remains_overridable():
    """The worker count must stay configurable, not hard-coded to 1."""
    command = _gateway_command()
    assert "${GATEWAY_WORKERS:-1}" in command, f"worker count must use ${{GATEWAY_WORKERS:-1}} so operators can override it; got: {command}"


def _graceful_shutdown_bound(launch: str) -> int:
    """Return uvicorn's ``--timeout-graceful-shutdown`` bound from a launch command or script."""
    match = re.search(r"--timeout-graceful-shutdown (\d+)", launch)
    assert match is not None, f"uvicorn launch must bound its graceful shutdown; got: {launch}"
    return int(match.group(1))


def _stop_grace_seconds(compose_path: Path) -> int:
    compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
    grace = compose["services"]["gateway"]["stop_grace_period"]
    match = re.fullmatch(r"(\d+)s", str(grace))
    assert match is not None, f"stop_grace_period must be expressed in seconds, got {grace!r}"
    return int(match.group(1))


def test_gateway_bounds_uvicorn_graceful_shutdown():
    """Open SSE connections must not hold lifespan shutdown (bounded hooks, run drain, memory flush) past the stop grace period."""
    assert _graceful_shutdown_bound(_gateway_command()) <= 30


def test_gateway_stop_grace_period_covers_the_shutdown_work():
    """Docker's 10s default SIGKILLed the 30s memory queue flush on every restart."""
    assert _stop_grace_seconds(COMPOSE_PATH) >= _graceful_shutdown_bound(_gateway_command()) + lifespan_shutdown_seconds()


def test_dev_gateway_bounds_uvicorn_graceful_shutdown_and_covers_it():
    """The dev stack launches uvicorn from dev-entrypoint.sh and is restarted far more often."""
    bound = _graceful_shutdown_bound(DEV_ENTRYPOINT_PATH.read_text(encoding="utf-8"))
    assert bound <= 30
    assert _stop_grace_seconds(DEV_COMPOSE_PATH) >= bound + lifespan_shutdown_seconds()


def test_shutdown_budget_models_every_bounded_lifespan_hook():
    """Each ``wait_for(..., timeout=_SHUTDOWN_HOOK_TIMEOUT_SECONDS)`` in the lifespan is a sequential 5s worst case the grace periods must cover."""
    source = GATEWAY_APP_PATH.read_text(encoding="utf-8")
    bounded_sites = source.count("timeout=_SHUTDOWN_HOOK_TIMEOUT_SECONDS")
    assert bounded_sites == len(HOOKS_BOUNDED_BY_SHUTDOWN_HOOK_TIMEOUT), (
        f"app.gateway.app bounds {bounded_sites} teardown hook(s) with _SHUTDOWN_HOOK_TIMEOUT_SECONDS but "
        f"_gateway_shutdown_budget models {len(HOOKS_BOUNDED_BY_SHUTDOWN_HOOK_TIMEOUT)}; update HOOKS_BOUNDED_BY_SHUTDOWN_HOOK_TIMEOUT "
        "so the chart and compose grace periods keep covering the worst case"
    )


# --- test_compose_extensions_config_writable ---

PROD_COMPOSE = REPO_ROOT / "docker" / "docker-compose.yaml"


EXTENSIONS_CONFIG_TARGET = "/app/backend/extensions_config.json"


APP_CONFIG_TARGET = "/app/backend/config.yaml"


def _gateway_volume_for(target: str) -> str:
    compose = yaml.safe_load(PROD_COMPOSE.read_text(encoding="utf-8"))
    volumes = compose["services"]["gateway"]["volumes"]
    matches = [str(entry) for entry in volumes if str(entry).split(":")[1:2] == [target]]
    assert len(matches) == 1, f"expected exactly one gateway mount for {target}, got {matches}"
    return matches[0]


def _mount_options(volume: str) -> set[str]:
    """Return the option flags of a short-syntax ``source:target[:options]`` mount.

    Options are comma-separated, so ``ro`` can legally appear as ``ro,z`` or
    ``z,ro``. Testing the raw string for a ``:ro`` suffix would read those as
    writable and let a read-only regression through.
    """
    parts = volume.split(":")
    if len(parts) < 3:
        return set()
    return {option.strip() for option in parts[2].split(",") if option.strip()}


@pytest.mark.parametrize(
    ("volume", "expected"),
    [
        ("./src:/dst", set()),
        ("./src:/dst:ro", {"ro"}),
        ("./src:/dst:ro,z", {"ro", "z"}),
        ("./src:/dst:z,ro", {"z", "ro"}),
        ("./src:/dst:rw", {"rw"}),
    ],
)
def test_mount_options_parses_comma_separated_flags(volume: str, expected: set[str]) -> None:
    assert _mount_options(volume) == expected


def test_extensions_config_is_mounted_writable() -> None:
    mount = _gateway_volume_for(EXTENSIONS_CONFIG_TARGET)
    assert "ro" not in _mount_options(mount), f"the Gateway writes {EXTENSIONS_CONFIG_TARGET} at runtime, so it must not be mounted read-only: {mount}"


def test_app_config_stays_read_only() -> None:
    mount = _gateway_volume_for(APP_CONFIG_TARGET)
    assert "ro" in _mount_options(mount), f"no API writes {APP_CONFIG_TARGET}; it must stay read-only: {mount}"


# --- test_compose_nginx_image_pin ---

EXACT_TAG = re.compile(r"^[^:]+:\d+\.\d+\.\d+(-[a-z]+)?$")


def test_nginx_image_is_pinned_to_an_exact_tag() -> None:
    for name, compose_path in COMPOSE_PATHS.items():
        compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
        image = (compose.get("services") or {}).get("nginx", {}).get("image")
        assert isinstance(image, str) and image, f"{name}: nginx service must declare an image"
        assert EXACT_TAG.match(image), f"{name}: nginx image {image!r} must pin an exact tag — a floating tag resolved to the musl-1.2.6 alpine build whose pwritev2 syscall older Docker seccomp profiles reject (#7615)"


def test_both_compose_files_pin_the_same_nginx_image() -> None:
    images = set()
    for compose_path in COMPOSE_PATHS.values():
        compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
        images.add((compose.get("services") or {}).get("nginx", {}).get("image"))
    assert len(images) == 1, "prod and dev compose files must pin the same nginx image"


# --- test_compose_nginx_ipv6_guard ---

HELM_NGINX_DEPLOYMENT = REPO_ROOT / "deploy" / "helm" / "deer-flow" / "templates" / "nginx-deployment.yaml"


NGINX_CONFS = {
    "compose": REPO_ROOT / "docker" / "nginx" / "nginx.conf",
    "helm": REPO_ROOT / "deploy" / "helm" / "deer-flow" / "templates" / "configmap-nginx.yaml",
}


GUARD_RE = re.compile(r"test -e /proc/net/if_inet6 \|\| sed -i '(?P<pattern>[^']+)' (?P<target>\S+)")


def _compose_nginx_script(compose_path: Path) -> str:
    compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
    command = compose["services"]["nginx"]["command"]
    if isinstance(command, list):
        assert command[:2] == ["sh", "-c"], f"{compose_path.name}: nginx command must be `sh -c <script>`; got {command[:2]!r}"
        return command[2]
    return str(command)


def _helm_nginx_script() -> str:
    # The template carries Helm expressions elsewhere; the nginx container's
    # ``args`` block is plain YAML, so pull the folded scalar out textually.
    text = HELM_NGINX_DEPLOYMENT.read_text(encoding="utf-8")
    match = re.search(r"args:\n\s+- >-\n((?:\s{14}.*\n)+)", text)
    assert match, "could not find the nginx args block in the Helm deployment"
    return " ".join(line.strip() for line in match.group(1).splitlines())


LAUNCHERS = {
    "prod": lambda: _compose_nginx_script(COMPOSE_PATHS["prod"]),
    "dev": lambda: _compose_nginx_script(COMPOSE_PATHS["dev"]),
    "helm": _helm_nginx_script,
}


def _guard(script: str) -> re.Match[str]:
    match = GUARD_RE.search(script)
    assert match, f"nginx launcher has no `test -e /proc/net/if_inet6 || sed -i ...` guard:\n{script}"
    return match


@pytest.mark.parametrize("launcher", sorted(LAUNCHERS))
def test_every_nginx_launcher_strips_the_ipv6_listen_when_ipv6_is_unavailable(launcher: str):
    script = LAUNCHERS[launcher]()

    guard = _guard(script)
    # The guard must run on the copied config, between the copy and the start.
    assert script.index("cp /etc/nginx/nginx.conf.template") < guard.start() < script.index("nginx -")
    start = script[guard.end() :]
    explicit = re.search(r"nginx (?:.*\s)?-c (\S+)", start)
    loaded = explicit.group(1) if explicit else "/etc/nginx/nginx.conf"  # nginx's compiled-in default
    assert guard.group("target") == loaded, f"the guard edits {guard.group('target')} but nginx loads {loaded}"


def test_all_nginx_launchers_use_one_identical_guard_pattern():
    """Three copies of one rule: pin them to the same sed expression so they cannot drift."""
    patterns = {launcher: _guard(script())["pattern"] for launcher, script in LAUNCHERS.items()}

    assert len(set(patterns.values())) == 1, f"nginx launchers disagree on the IPv6 guard pattern: {patterns}"


@pytest.mark.parametrize("variant", sorted(COMPOSE_PATHS))
def test_compose_nginx_execs_nginx_as_pid_1(variant: str):
    """`exec` hands PID 1 to nginx so `docker stop` delivers SIGTERM/SIGQUIT to it, not to `sh`."""
    script = _compose_nginx_script(COMPOSE_PATHS[variant])

    assert re.search(r"(^|\n|&&\s*)exec nginx -g 'daemon off;'", script), f"{variant} compose must start nginx with `exec`:\n{script}"
    assert "set -e" in script, f"{variant} compose must fail the container when the copy or the guard fails:\n{script}"


def _apply_sed_delete(bre_pattern: str, text: str) -> str:
    """Apply `sed -i '/<pattern>/d'` with Python's regex engine (BusyBox BRE → Python re)."""
    assert bre_pattern.startswith("/") and bre_pattern.endswith("/d"), bre_pattern
    body = bre_pattern[1:-2].replace("[[:space:]]", r"\s").replace(r"\+", "+")
    return "".join(line for line in text.splitlines(keepends=True) if not re.search(body, line))


@pytest.mark.parametrize("conf", sorted(NGINX_CONFS))
def test_guard_pattern_removes_only_the_ipv6_listen_from_the_shipped_config(conf: str):
    """The pattern is only useful if it matches the exact `listen [::]:2026 ...;` line we ship."""
    pattern = _guard(LAUNCHERS["dev"]())["pattern"]
    original = NGINX_CONFS[conf].read_text(encoding="utf-8")
    assert re.search(r"^\s*listen \[::\]:2026 default_server;\s*$", original, re.M), f"{conf} nginx config no longer has the IPv6 listen this guard targets"

    stripped = _apply_sed_delete(pattern, original)

    assert not re.search(r"^\s*listen\s+\[::\]", stripped, re.M), f"{conf}: IPv6 listen survived the guard"
    assert re.search(r"^\s*listen 2026 default_server;\s*$", stripped, re.M), f"{conf}: the IPv4 listen must survive"
    assert len(original.splitlines()) - len(stripped.splitlines()) == 1
