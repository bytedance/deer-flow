"""Host-name case must not decide whether an address is local.

`_LOCAL_HTTP_HOSTS` holds lowercase names and both membership tests were exact string
compares, so a local endpoint spelled with any uppercase letter read as an external one:
`declaration-external-endpoint` on a local URL, `network-cleartext-http` instead of
`network-local-http`, and — for a script that also reads a sensitive path — a blocking
`python-sensitive-exfil` instead of the `python-sensitive-path-read` the same file gets
when the host is written in lowercase.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from deerflow.skills.skillscan.orchestrator import _http_host, _is_outbound_url, scan_skill_dir

LOCAL_SPELLINGS = [
    "http://localhost:8080/api",
    "http://LOCALHOST:8080/api",
    "http://LocalHost:8080/api",
    "http://lOcAlHoSt:8080/api",
    "http://127.0.0.1:8080/api",
]

EXTERNAL_SPELLINGS = [
    "http://example.com/x",
    "http://Example.COM/x",
    "https://example.com/x",
]


def _rules(root: Path) -> list[tuple[str, str]]:
    return sorted({(finding["rule_id"], finding["severity"]) for finding in scan_skill_dir(root)["findings"]})


def _package(tmp_path: Path, *, skill_md_body: str = "Body.\n", extra: tuple[str, str] | None = None) -> Path:
    root = tmp_path / "pkg"
    root.mkdir(parents=True)
    (root / "SKILL.md").write_text(f"---\nname: demo\ndescription: A demo skill\n---\n\n{skill_md_body}", encoding="utf-8")
    if extra is not None:
        (root / extra[0]).write_text(extra[1], encoding="utf-8")
    return root


@pytest.mark.parametrize(
    ("url", "host"),
    [
        ("http://localhost:8080/api", "localhost"),
        ("http://LOCALHOST:8080/api", "localhost"),
        ("http://LocalHost:8080/api", "localhost"),
        ("http://lOcAlHoSt:8080/api", "localhost"),
        ("http://127.0.0.1:8080/api", "127.0.0.1"),
        ("http://Example.COM/x", "example.com"),
    ],
)
def test_http_host_is_lowercased(url: str, host: str) -> None:
    assert _http_host(url) == host


@pytest.mark.parametrize("url", LOCAL_SPELLINGS)
def test_local_spelling_is_not_outbound(url: str) -> None:
    assert _is_outbound_url(url) is False


@pytest.mark.parametrize("url", EXTERNAL_SPELLINGS)
def test_external_spelling_stays_outbound(url: str) -> None:
    assert _is_outbound_url(url) is True


@pytest.mark.parametrize("url", LOCAL_SPELLINGS)
def test_local_spelling_is_not_an_external_endpoint(tmp_path: Path, url: str) -> None:
    root = _package(tmp_path, skill_md_body=f"Call {url} for status.\n")

    assert _rules(root) == [("network-local-http", "LOW")]


@pytest.mark.parametrize("url", LOCAL_SPELLINGS)
def test_local_spelling_does_not_become_an_exfil_sink(tmp_path: Path, url: str) -> None:
    root = _package(tmp_path, extra=("run.py", f'ENDPOINT = "{url}"\n\nopen("/etc/passwd").read()\n'))

    rules = _rules(root)

    assert ("python-sensitive-exfil", "CRITICAL") not in rules
    assert ("python-sensitive-path-read", "HIGH") in rules


def test_external_host_is_still_an_exfil_sink(tmp_path: Path) -> None:
    """Precision: lowercasing the host must not stop a real external sink being a sink."""
    root = _package(tmp_path, extra=("run.py", 'ENDPOINT = "http://Example.COM/x"\n\nopen("/etc/passwd").read()\n'))

    assert ("python-sensitive-exfil", "CRITICAL") in _rules(root)


def test_external_spelling_is_still_an_external_endpoint(tmp_path: Path) -> None:
    """Precision: lowercasing the host must not stop a real external endpoint being reported."""
    root = _package(tmp_path, skill_md_body="Call http://Example.COM/x for status.\n")

    assert ("declaration-external-endpoint", "MEDIUM") in _rules(root)
