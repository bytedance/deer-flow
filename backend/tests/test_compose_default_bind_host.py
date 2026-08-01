"""Regression test for the Docker Compose default published bind address.

``README.md`` documents DeerFlow as being deployed by default "in a local
trusted environment (accessible only via the 127.0.0.1 loopback interface)",
but the shipped compose files published the nginx entry as
``"${PORT:-2026}:2026"``, which Docker binds to ``0.0.0.0`` (and ``[::]``). The
shipped artifact therefore did not match its own documented default, and an
operator running it on a LAN or cloud host got a wider surface than the docs
implied without changing anything.

The Gateway itself binds ``0.0.0.0`` inside the container on purpose (nginx has
to reach it over the compose network) and its port is deliberately not
published, so the published nginx port is the whole external surface. This test
pins the loopback default there while keeping it overridable for operators who
intentionally expose the stack behind their own TLS/auth front door.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_PATHS = {
    "prod": REPO_ROOT / "docker" / "docker-compose.yaml",
    "dev": REPO_ROOT / "docker" / "docker-compose-dev.yaml",
}

EXPECTED_NGINX_PORT_MAPPING = "${BIND_HOST:-127.0.0.1}:${PORT:-2026}:2026"


def _published_ports(compose_path: Path) -> dict[str, list[str]]:
    """Return {service_name: [port mapping, ...]} for every published port."""
    compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
    published: dict[str, list[str]] = {}
    for service_name, service in (compose.get("services") or {}).items():
        ports = service.get("ports") if isinstance(service, dict) else None
        if not ports:
            continue
        published[service_name] = [str(entry) for entry in ports]
    return published


@pytest.mark.parametrize("variant", sorted(COMPOSE_PATHS))
def test_nginx_entry_defaults_to_loopback(variant: str):
    """With BIND_HOST unset, the entry port must bind 127.0.0.1, not 0.0.0.0."""
    published = _published_ports(COMPOSE_PATHS[variant])

    assert published.get("nginx") == [EXPECTED_NGINX_PORT_MAPPING], f"{variant} compose must publish nginx as {EXPECTED_NGINX_PORT_MAPPING!r}; got: {published.get('nginx')!r}"


@pytest.mark.parametrize("variant", sorted(COMPOSE_PATHS))
def test_no_service_publishes_on_all_interfaces(variant: str):
    """No compose service may publish a port without an explicit bind address.

    A bare ``"HOST:CONTAINER"`` mapping binds every interface. Any port added
    later must either stay internal to the compose network or opt in to the
    same ``BIND_HOST`` default.
    """
    offenders: list[str] = []
    for service_name, mappings in _published_ports(COMPOSE_PATHS[variant]).items():
        for mapping in mappings:
            # A bind address is present only when the mapping has three
            # colon-separated parts (``ADDR:HOST:CONTAINER``). Variable
            # substitutions such as ``${PORT:-2026}`` also contain colons, so
            # count separators outside ``${...}`` instead of splitting naively.
            if _bind_address(mapping) is None:
                offenders.append(f"{service_name}: {mapping}")

    assert not offenders, f"{variant} compose publishes ports on all interfaces (add a bind address): {offenders}"


@pytest.mark.parametrize("variant", sorted(COMPOSE_PATHS))
def test_bind_address_remains_overridable(variant: str):
    """Operators fronting the stack themselves must be able to widen the bind."""
    mapping = _published_ports(COMPOSE_PATHS[variant])["nginx"][0]

    assert _bind_address(mapping) == "${BIND_HOST:-127.0.0.1}", f"{variant} compose must keep the bind address overridable via BIND_HOST; got: {mapping!r}"


def _bind_address(mapping: str) -> str | None:
    """Return the bind-address segment of a compose port mapping, if any.

    Splits on ``:`` at nesting depth zero so ``${PORT:-2026}`` is treated as a
    single segment rather than two.
    """
    segments: list[str] = []
    current: list[str] = []
    depth = 0
    index = 0
    while index < len(mapping):
        char = mapping[index]
        if mapping.startswith("${", index):
            depth += 1
            current.append("${")
            index += 2
            continue
        if char == "}" and depth > 0:
            depth -= 1
        elif char == ":" and depth == 0:
            segments.append("".join(current))
            current = []
            index += 1
            continue
        current.append(char)
        index += 1
    segments.append("".join(current))

    # ADDR:HOST:CONTAINER -> bound; HOST:CONTAINER or CONTAINER -> unbound.
    return segments[0] if len(segments) >= 3 else None
