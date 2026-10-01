"""Loopback host canonicalization shared by the three nginx configs (#6156).

Browsers scope cookies per host, so serving both ``localhost:2026`` and
``127.0.0.1:2026`` (or ``[::1]:2026``) splits the login session into separate
jars. The proxy canonicalizes the numeric spellings onto ``localhost`` with a
301, safe methods only: a redirected API POST would strand clients that do not
re-send bodies, and non-loopback Hosts (LAN names, ingress domains) must never
match. The canonical target itself must not match either, or the redirect
would loop.
"""

from __future__ import annotations

import re

import pytest
from support.nginx_conf import NGINX_CONFIGS, read_config


def _extract_block(content: str, marker: re.Pattern[str]) -> str:
    """Return the brace-balanced block whose header matches ``marker``."""
    match = marker.search(content)
    assert match, f"could not find block matching {marker.pattern!r}"
    start = match.end() - 1  # index of the opening brace
    depth = 0
    for i, ch in enumerate(content[start:], start=start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return content[start : i + 1]
    raise AssertionError(f"unbalanced braces after {marker.pattern!r}")


def _extract_map(content: str, variable: str) -> list[tuple[str, str]]:
    """Entries of ``map ... $<variable> { ... }`` as ``(selector, value)`` pairs."""
    body = _extract_block(content, re.compile(r"map\s+\S+\s+\$" + re.escape(variable) + r"\s*\{"))
    entries = []
    for line in body[1:-1].splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        selector, value = line.rstrip(";").split(None, 1)
        entries.append((selector.strip('"'), value.strip().strip('"')))
    return entries


def _nginx_regex(selector: str) -> re.Pattern[str] | None:
    """Translate an nginx map regex selector (``~``/``~*``) into a Python pattern."""
    if selector.startswith("~*"):
        return re.compile(selector[2:].replace("(?<", "(?P<"), re.IGNORECASE)
    if selector.startswith("~"):
        return re.compile(selector[1:].replace("(?<", "(?P<"))
    return None


def _evaluate_map(entries: list[tuple[str, str]], key: str) -> str:
    """nginx map semantics: exact strings win first, then regexes in file order."""
    default = ""
    regexes: list[tuple[re.Pattern[str], str]] = []
    for selector, value in entries:
        if selector == "default":
            default = value
            continue
        pattern = _nginx_regex(selector)
        if pattern is None:
            if selector == key:
                return value
        else:
            regexes.append((pattern, value))
    for pattern, value in regexes:
        match = pattern.search(key)
        if match:
            for name, group in match.groupdict().items():
                if group is not None:
                    value = value.replace(f"${name}", group)
            return value
    return default


def _canonical_origin(content: str, method: str, host: str, upgrade: str = "") -> str:
    """The redirect target the two-map pipeline produces, or "" for no redirect."""
    canonical_host = _evaluate_map(_extract_map(content, "loopback_canonical_host"), host)
    origin = _evaluate_map(_extract_map(content, "loopback_origin"), f"{method}:{upgrade}:{canonical_host}")
    return origin.replace("$loopback_canonical_host", canonical_host)


@pytest.mark.parametrize("config_path", NGINX_CONFIGS)
@pytest.mark.parametrize(
    ("method", "host", "expected"),
    [
        # The reported split: both spellings serve :2026, cookies do not follow.
        ("GET", "127.0.0.1:2026", "localhost:2026"),
        ("HEAD", "127.0.0.1:2026", "localhost:2026"),
        ("GET", "127.0.0.1", "localhost"),
        ("GET", "[::1]:2026", "localhost:2026"),
        ("GET", "[::1]", "localhost"),
        # Docker publishes an arbitrary host port; it must survive the redirect.
        ("GET", "127.0.0.1:18080", "localhost:18080"),
        # API clients re-sending no bodies must never be redirected mid-POST.
        ("POST", "127.0.0.1:2026", ""),
        ("PUT", "[::1]:2026", ""),
        # The canonical target must not match: that would be a redirect loop.
        ("GET", "localhost:2026", ""),
        ("GET", "localhost", ""),
        # LAN names and ingress domains stay untouched.
        ("GET", "deerflow.lan:2026", ""),
        ("GET", "deerflow.example.com", ""),
        # Suffix spoofs of the numeric spelling must not match.
        ("GET", "127.0.0.1.evil.example", ""),
        ("GET", "evil-127.0.0.1.example:2026", ""),
    ],
)
def test_loopback_canonicalization(config_path: str, method: str, host: str, expected: str) -> None:
    assert _canonical_origin(read_config(config_path), method, host) == expected


@pytest.mark.parametrize("config_path", NGINX_CONFIGS)
@pytest.mark.parametrize("host", ["127.0.0.1:2026", "[::1]:2026", "127.0.0.1:18080"])
def test_websocket_handshake_is_not_redirected(config_path: str, host: str) -> None:
    # WS clients do not follow 301s; the upgrade request must reach the proxy as-is.
    assert _canonical_origin(read_config(config_path), "GET", host, upgrade="websocket") == ""


@pytest.mark.parametrize("config_path", NGINX_CONFIGS)
def test_main_server_redirects_to_the_canonical_origin(config_path: str) -> None:
    content = read_config(config_path)
    server = _extract_block(content, re.compile(r"server\s*\{(?=[^}]*?listen\s+(?:\[::\]:)?2026\b)"))
    assert 'if ($loopback_origin != "")' in server
    assert "return 301 $scheme://$loopback_origin$request_uri;" in server


def test_canonicalization_maps_match_across_configs() -> None:
    """The three maintained configs carry the same routing and must not drift."""
    per_config = [
        (
            _extract_map(read_config(path), "loopback_canonical_host"),
            _extract_map(read_config(path), "loopback_origin"),
        )
        for path in NGINX_CONFIGS
    ]
    assert all(entries == per_config[0] for entries in per_config[1:])
