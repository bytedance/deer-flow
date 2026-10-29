"""Line-oriented `secret-env-assignment` sweep: every spelling of the same binding.

The rule runs over text (`_scan_secret_assignments_by_text`), so the *format* must not
decide whether a credential is reported: `api_key: <secret>` in YAML, `API_KEY=<secret>`
in `.env`/`.ini`/shell and `{"api_key": "<secret>"}` in JSON are the same binding and have
to read the same way. The quoted-key shapes below are what a JSON config uses.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deerflow.skills.skillscan.orchestrator import _SECRET_ASSIGNMENT_RE, scan_skill_dir

SECRET = "9f8e7d6c5b4a3210ff"

# Key on the left, value on the right, with the key quoted the way each format spells it.
QUOTED_KEY_CASES = [
    ("config.json", '{"api_key": "%s"}'),
    ("token.json", '{"token": "%s"}'),
    ("plural.json", '{"secrets": "%s"}'),
    ("password.json", '{"password": "%s"}'),
    ("hyphen.json", '{"api-key": "%s"}'),
    ("single.json", "{'api_key': '%s'}"),
    ("spaced.json", '{"api_key" : "%s"}'),
    ("nested.json", '{"auth": {"api_key": "%s"}}'),
    ("inline.json", '{"api_key": "%s", "other": 1}'),
]

UNQUOTED_KEY_CASES = [
    ("config.yaml", "api_key: %s"),
    ("config.ini", "api_key=%s"),
    ("app.env", "API_KEY=%s"),
]

# Shapes the rule must keep quiet about, so the quoted-key match does not become a blanket
# "any JSON string" match.
QUIET_CASES = [
    ("placeholder.json", '{"api_key": "your-key-here"}'),
    ("env-ref.json", '{"api_key": "${API_KEY}"}'),
    ("empty.json", '{"api_key": ""}'),
    ("unrelated.json", '{"other": "%s"}'),
]

# The credential word is often the tail of a longer name separated by `_`, `.` or `-`
# (`access_token`, `client_secret`, `x-api-key`). Those are the common spellings in OAuth
# and service-account config, and each must read the same as the bare name.
SUFFIXED_KEY_CASES = [
    ("oauth.json", '{"access_token": "%s"}'),
    ("client.json", '{"client_secret": "%s"}'),
    ("refresh.json", '{"refresh_token": "%s"}'),
    ("access.env", "ACCESS_TOKEN=%s"),
    ("client.env", "CLIENT_SECRET=%s"),
    ("api.env", "MY_API_KEY=%s"),
    ("client.yaml", "client_secret: %s"),
    ("access.ini", "access_token=%s"),
    ("dotted.yaml", "auth.token: %s"),
    ("hyphen.yaml", "x-api-key: %s"),
]

# A run of letters before the credential word is not a credential name: the sweep must not
# fire on ordinary words that merely contain the keyword (`tokenizer`, `secretive`).
MIDWORD_QUIET_CASES = [
    ("tokenizer.yaml", "tokenizer: %s"),
    ("secretive.yaml", "secretive: %s"),
    ("passwordless.yaml", "passwordless: %s"),
    ("credentials_file.yaml", "credentials_file: %s"),
    ("mytoken.yaml", "mytoken: %s"),
]


def _write_package(parent: Path, filename: str, text: str) -> Path:
    root = parent / "pkg"
    root.mkdir(parents=True, exist_ok=True)
    (root / "SKILL.md").write_text("---\nname: demo\ndescription: A demo skill\n---\n\nBody.\n", encoding="utf-8")
    (root / filename).write_text(text + "\n", encoding="utf-8")
    return root


def _secret_findings(root: Path) -> list[dict]:
    return [finding for finding in scan_skill_dir(root)["findings"] if finding["rule_id"] == "secret-env-assignment"]


@pytest.mark.parametrize(("filename", "template"), QUOTED_KEY_CASES)
def test_quoted_key_is_reported(tmp_path: Path, filename: str, template: str) -> None:
    root = _write_package(tmp_path, filename, template % SECRET)

    assert [(finding["rule_id"], finding["line"]) for finding in _secret_findings(root)] == [("secret-env-assignment", 1)]


@pytest.mark.parametrize(("filename", "template"), UNQUOTED_KEY_CASES)
def test_unquoted_key_stays_reported(tmp_path: Path, filename: str, template: str) -> None:
    root = _write_package(tmp_path, filename, template % SECRET)

    assert [(finding["rule_id"], finding["line"]) for finding in _secret_findings(root)] == [("secret-env-assignment", 1)]


@pytest.mark.parametrize(("filename", "template"), SUFFIXED_KEY_CASES)
def test_separator_prefixed_key_is_reported(tmp_path: Path, filename: str, template: str) -> None:
    root = _write_package(tmp_path, filename, template % SECRET)

    assert [(finding["rule_id"], finding["line"]) for finding in _secret_findings(root)] == [("secret-env-assignment", 1)]


@pytest.mark.parametrize(("filename", "template"), MIDWORD_QUIET_CASES)
def test_midword_key_stays_quiet(tmp_path: Path, filename: str, template: str) -> None:
    root = _write_package(tmp_path, filename, template % SECRET)

    assert _secret_findings(root) == []


@pytest.mark.parametrize(
    "text",
    [
        '{"access_token": "' + SECRET + '"}',
        '{"client_secret": "' + SECRET + '"}',
        "ACCESS_TOKEN=" + SECRET,
        "MY_API_KEY=" + SECRET,
    ],
)
def test_sweep_matches_separator_prefixed_keys(text: str) -> None:
    """The review's shapes: a separator may introduce the credential word."""
    assert [match.group(2) for match in _SECRET_ASSIGNMENT_RE.finditer(text)] == [SECRET]


@pytest.mark.parametrize("word", ["tokenizer", "secretive", "passwordless", "mytoken"])
def test_sweep_ignores_a_letter_run_before_the_word(word: str) -> None:
    """A letter run is not a separator, so the word boundary still holds."""
    assert list(_SECRET_ASSIGNMENT_RE.finditer(f"{word}: {SECRET}")) == []


@pytest.mark.parametrize(("filename", "template"), QUIET_CASES)
def test_non_credential_or_placeholder_values_stay_quiet(tmp_path: Path, filename: str, template: str) -> None:
    root = _write_package(tmp_path, filename, template % SECRET if "%s" in template else template)

    assert _secret_findings(root) == []


def test_json_key_spelling_reports_the_same_finding_as_yaml(tmp_path: Path) -> None:
    """The format alone must not decide whether the binding is reported."""
    yaml_root = _write_package(tmp_path / "yaml", "config.yaml", f"api_key: {SECRET}")
    json_root = _write_package(tmp_path / "json", "config.json", '{"api_key": "' + SECRET + '"}')

    assert [finding["line"] for finding in _secret_findings(yaml_root)] == [1]
    assert [finding["line"] for finding in _secret_findings(json_root)] == [1]


def test_pretty_printed_json_reports_the_line_the_key_is_on(tmp_path: Path) -> None:
    root = _write_package(tmp_path, "config.json", '{\n  "api_key": "' + SECRET + '"\n}')

    assert [finding["line"] for finding in _secret_findings(root)] == [2]


@pytest.mark.parametrize("name", ["tokens", "total_tokens", "input_tokens", "output_tokens", "prompt_tokens", "completion_tokens", "cached_tokens", "reasoning_tokens"])
@pytest.mark.parametrize("value", [0, 84852])
@pytest.mark.parametrize("template", ['{"%s": %s}', '{\n  "%s": %s,\n  "duration_ms": 23332\n}', "%s: %s", "%s=%s"])
def test_numeric_model_token_counts_are_not_credentials(tmp_path: Path, name: str, value: int, template: str) -> None:
    root = _write_package(tmp_path, "measurements.md", template % (name.upper() if "=" in template else name, value))

    assert _secret_findings(root) == []


@pytest.mark.parametrize(
    "text",
    [
        '{"total_tokens": "84852"}',
        '{"total_tokens": "' + SECRET + '"}',
        "total_tokens: 84852secret",
        "access_tokens: 84852",
        "api_key: 84852",
        "password: 84852",
        "access_total_tokens: 84852",
        '{"access total_tokens": 84852}',
        '{"access/total_tokens": 84852}',
        '{"tokens": "84852"}',
        '{"tokens": {"mean": "' + SECRET + '", "stddev": 1, "min": 0, "max": 2}}',
        '{"tokens": {"api_key": "' + SECRET + '"}}',
        '{"tokens": {"mean": true, "stddev": 1, "min": 0, "max": 2}}',
        '{"tokens": {"mean": NaN, "stddev": 1, "min": 0, "max": 2}}',
        '{"tokens": {"mean": 1e999, "stddev": 1, "min": 0, "max": 2}}',
        '{"tokens": {"mean": "' + SECRET + '", "mean": 1, "stddev": 1, "min": 0, "max": 2}}',
        '{"tokens": [["mean", 1], ["stddev", 1], ["min", 0], ["max", 2]]}',
        '{"tokens": "+1700' + SECRET + '"}',
    ],
)
def test_token_count_exemption_preserves_credential_detection(tmp_path: Path, text: str) -> None:
    root = _write_package(tmp_path, "config.md", text)

    assert [finding["line"] for finding in _secret_findings(root)] == [1]


def test_numeric_token_count_does_not_hide_later_credential(tmp_path: Path) -> None:
    root = _write_package(tmp_path, "config.md", '{"total_tokens": 84852}\napi_key: ' + SECRET)

    assert [finding["line"] for finding in _secret_findings(root)] == [2]


def test_numeric_token_count_does_not_suppress_cloud_token_scan(tmp_path: Path) -> None:
    token = "sk-" + "a1b2c3d4" * 4
    root = _write_package(tmp_path, "config.md", '{"total_tokens": 84852}\nAuthorization: Bearer ' + token)

    findings = scan_skill_dir(root)["findings"]

    assert any(finding["rule_id"] == "secret-cloud-token" and finding["severity"] == "CRITICAL" for finding in findings)


@pytest.mark.parametrize("value", [{"mean": 3800.5, "stddev": 400, "min": 3200, "max": 4100}, "+1700", "-12.5"])
def test_benchmark_token_summaries_are_measurements(tmp_path: Path, value) -> None:
    root = _write_package(tmp_path, "benchmark.md", json.dumps({"tokens": value}))

    assert _secret_findings(root) == []
