"""Tests for scripts/support_bundle.py."""

from __future__ import annotations

import json
import zipfile

import pytest
import support_bundle


def _zip_text(zip_path, name: str) -> str:
    with zipfile.ZipFile(zip_path) as zf:
        return zf.read(name).decode("utf-8")


def test_redact_data_recursively_masks_secret_like_keys():
    data = {
        "models": [
            {
                "name": "default",
                "api_key": "sk-live-secret",
                "nested": {
                    "client_secret": "client-secret-value",
                    "safe": "visible",
                },
            }
        ],
        "headers": {
            "Authorization": "Bearer header-secret",
        },
        "plain": "kept",
    }

    redacted = support_bundle.redact_data(data)

    assert redacted["models"][0]["api_key"] == "<redacted>"
    assert redacted["models"][0]["nested"]["client_secret"] == "<redacted>"
    assert redacted["models"][0]["nested"]["safe"] == "visible"
    assert redacted["headers"]["Authorization"] == "<redacted>"
    assert redacted["plain"] == "kept"


def test_redact_data_masks_url_credentials_and_cli_flag_secrets():
    data = {
        "models": [
            {"name": "m", "base_url": "https://admin:S3cr3tPass@proxy.internal/v1"},
            {"name": "n", "endpoint": "https://host/v1?access_token=AKIA1234567890ABCD"},
            {"name": "h", "default_headers": {"X-My-Auth": "rawsecrettoken123"}},
        ],
        "database_url": "postgres://dfuser:dfpass@db:5432/deer",
        "mcpServers": {
            "svc": {"command": "npx", "args": ["-y", "server", "--api-key", "LIVE-MCP-SECRET-XYZ"]},
        },
    }

    redacted = support_bundle.redact_data(data)

    assert redacted["models"][0]["base_url"] == "https://<redacted>@proxy.internal/v1"
    assert "AKIA1234567890ABCD" not in redacted["models"][1]["endpoint"]
    assert redacted["models"][1]["endpoint"].endswith("access_token=<redacted>")
    assert redacted["models"][2]["default_headers"]["X-My-Auth"] == "<redacted>"
    assert "dfpass" not in redacted["database_url"]
    assert redacted["database_url"] == "postgres://<redacted>@db:5432/deer"
    args = redacted["mcpServers"]["svc"]["args"]
    assert args[:3] == ["-y", "server", "--api-key"]
    assert args[3] == "<redacted>"


def test_redact_data_masks_inline_and_credential_only_url_secrets():
    data = {
        "mcpServers": {
            "svc": {"command": "npx", "args": ["server", "--api-key=LIVE-COMBINED-SECRET"]},
        },
        "cache_url": "redis://:SuperSecretPass@cache:6379/0",
    }

    redacted = support_bundle.redact_data(data)

    assert "LIVE-COMBINED-SECRET" not in json.dumps(redacted)
    assert redacted["mcpServers"]["svc"]["args"][1] == "--api-key=<redacted>"
    assert "SuperSecretPass" not in redacted["cache_url"]
    assert redacted["cache_url"] == "redis://<redacted>@cache:6379/0"


def test_redact_text_masks_url_userinfo_and_query_secrets():
    text = "\n".join(
        [
            "base_url: https://admin:S3cr3tPass@proxy.internal/v1",
            "postgres://dfuser:dfpass@db:5432/deer",
            "endpoint: https://host/v1?api_key=LIVE-QUERY-SECRET&model=gpt-4o",
        ]
    )

    redacted = support_bundle.redact_text(text)

    assert "S3cr3tPass" not in redacted
    assert "dfpass" not in redacted
    assert "LIVE-QUERY-SECRET" not in redacted
    assert "https://<redacted>@proxy.internal/v1" in redacted
    assert "model=gpt-4o" in redacted


def test_redact_keeps_non_secret_flags_visible():
    redacted = support_bundle.redact_data(["--model", "gpt-4o", "--verbose"])
    assert redacted == ["--model", "gpt-4o", "--verbose"]


def test_redact_text_masks_env_assignments_and_bearer_tokens():
    text = "\n".join(
        [
            "OPENAI_API_KEY=sk-live-secret",
            "Authorization: Bearer abc.def.ghi",
            "client_secret: very-secret",
            "normal=value",
        ]
    )

    redacted = support_bundle.redact_text(text)

    assert "sk-live-secret" not in redacted
    assert "abc.def.ghi" not in redacted
    assert "very-secret" not in redacted
    assert "OPENAI_API_KEY=<redacted>" in redacted
    assert "Authorization: Bearer <redacted>" in redacted
    assert "normal=value" in redacted


def test_redact_text_masks_home_directory_paths():
    text = "\n".join(
        [
            "/Users/alice/deer-flow/config.yaml",
            "/home/bob/deer-flow/config.yaml",
            r"C:\Users\carol\deer-flow\config.yaml",
        ]
    )

    redacted = support_bundle.redact_text(text)

    assert "alice" not in redacted
    assert "bob" not in redacted
    assert "carol" not in redacted
    assert "/Users/<user>/deer-flow/config.yaml" in redacted
    assert "/home/<user>/deer-flow/config.yaml" in redacted
    assert r"C:\Users\<user>\deer-flow\config.yaml" in redacted


def test_redact_data_masks_non_keyword_env_secrets_but_keeps_var_references():
    data = {
        "mcpServers": {
            "supabase": {
                "command": "npx",
                "env": {
                    "SUPABASE_SERVICE_ROLE_KEY": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.payload.sig",
                    "R2_ACCESS_KEY": "0123456789abcdef0123456789abcdef",
                    "GEMINI_KEY": "AIzaSyA-EXAMPLE-hardcoded-google-key",
                    "PROJECT_REF": "$SUPABASE_PROJECT_REF",
                    "REGION": "${AWS_REGION}",
                },
            }
        }
    }

    redacted = support_bundle.redact_data(data)
    env = redacted["mcpServers"]["supabase"]["env"]

    assert env["SUPABASE_SERVICE_ROLE_KEY"] == "<redacted>"
    assert env["R2_ACCESS_KEY"] == "<redacted>"
    assert env["GEMINI_KEY"] == "<redacted>"
    assert env["PROJECT_REF"] == "$SUPABASE_PROJECT_REF"
    assert env["REGION"] == "${AWS_REGION}"

    dumped = json.dumps(redacted)
    assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in dumped
    assert "0123456789abcdef" not in dumped
    assert "AIzaSyA-EXAMPLE-hardcoded-google-key" not in dumped


def test_redact_data_masks_broadened_secret_key_names():
    data = {
        "aws_access_key_id": "AKIAIOSFODNN7EXAMPLE",
        "db_pwd": "hunter2",
        "signing_private_key": "-----BEGIN KEY-----abc-----END KEY-----",
    }

    redacted = support_bundle.redact_data(data)

    assert redacted["aws_access_key_id"] == "<redacted>"
    assert redacted["db_pwd"] == "<redacted>"
    assert redacted["signing_private_key"] == "<redacted>"


def test_create_support_bundle_masks_hardcoded_env_secret(tmp_path):
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / "config.yaml").write_text(
        "config_version: 5\nmodels:\n  - name: default\n",
        encoding="utf-8",
    )
    (project_root / "extensions_config.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "supabase": {
                        "command": "npx",
                        "env": {
                            "SUPABASE_SERVICE_ROLE_KEY": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.leak.sig",
                            "R2_ACCESS_KEY": "0123456789abcdef0123456789abcdef",
                            "PROJECT_REF": "$SUPABASE_PROJECT_REF",
                        },
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    output_path = tmp_path / "support.zip"
    support_bundle.create_support_bundle(
        project_root=project_root,
        out_path=output_path,
        include_doctor=False,
    )

    all_text = "\n".join(_zip_text(output_path, name) for name in zipfile.ZipFile(output_path).namelist())
    assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.leak.sig" not in all_text
    assert "0123456789abcdef" not in all_text

    extensions_summary = json.loads(_zip_text(output_path, "extensions-summary.json"))
    env = extensions_summary["mcpServers"]["supabase"]["env"]
    assert env["SUPABASE_SERVICE_ROLE_KEY"] == "<redacted>"
    assert env["R2_ACCESS_KEY"] == "<redacted>"
    assert env["PROJECT_REF"] == "$SUPABASE_PROJECT_REF"


def test_create_support_bundle_writes_sanitized_zip(tmp_path):
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / "config.yaml").write_text(
        """
config_version: 5
models:
  - name: default
    use: langchain_openai:ChatOpenAI
    model: gpt-4o
    api_key: sk-live-secret
tools:
  - name: web_search
    use: deerflow.community.brave.tools:web_search_tool
    api_key: brave-secret
channels:
  slack:
    enabled: true
    bot_token: xoxb-secret
""",
        encoding="utf-8",
    )
    (project_root / "extensions_config.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "private": {
                        "command": "node",
                        "env": {
                            "PRIVATE_TOKEN": "mcp-secret",
                        },
                    }
                },
                "skills": {
                    "public:research": {
                        "enabled": True,
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    output_path = tmp_path / "support.zip"
    bundle_path = support_bundle.create_support_bundle(
        project_root=project_root,
        out_path=output_path,
        thread_id=None,
        include_doctor=False,
    )

    assert bundle_path == output_path
    with zipfile.ZipFile(bundle_path) as zf:
        names = set(zf.namelist())

    assert {
        "manifest.json",
        "environment.json",
        "config-summary.json",
        "extensions-summary.json",
        "git.json",
    }.issubset(names)

    all_text = "\n".join(_zip_text(bundle_path, name) for name in names if name.endswith(".json"))
    assert "sk-live-secret" not in all_text
    assert "brave-secret" not in all_text
    assert "xoxb-secret" not in all_text
    assert "mcp-secret" not in all_text

    config_summary = json.loads(_zip_text(bundle_path, "config-summary.json"))
    assert config_summary["models"][0]["api_key"] == "<redacted>"
    assert config_summary["tools"][0]["api_key"] == "<redacted>"
    assert config_summary["channels"]["slack"]["bot_token"] == "<redacted>"


def test_create_support_bundle_writes_ai_triage_entrypoints(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    project_root.mkdir()

    monkeypatch.setattr(
        support_bundle,
        "collect_environment",
        lambda _project_root: {
            "platform": {
                "system": "Darwin",
                "release": "25.5.0",
                "machine": "arm64",
                "python": "3.12.11",
            },
            "commands": [
                {"name": "node", "ok": True, "stdout": "v20.19.5", "stderr": ""},
                {"name": "pnpm", "ok": True, "stdout": "11.7.0", "stderr": ""},
                {"name": "uv", "ok": True, "stdout": "uv 0.8.11", "stderr": ""},
                {"name": "nginx", "ok": True, "stdout": "", "stderr": "nginx version: nginx/1.31.1"},
                {"name": "docker", "ok": False, "error": "docker not found"},
            ],
        },
    )
    monkeypatch.setattr(
        support_bundle,
        "collect_git_summary",
        lambda _project_root: {
            "branch": {"ok": True, "stdout": "feat/community-support-bundle", "stderr": ""},
            "head": {"ok": True, "stdout": "abc123", "stderr": ""},
            "upstream": {"ok": True, "stdout": "origin/main", "stderr": ""},
            "status_short": {"ok": True, "stdout": "## feat/community-support-bundle...origin/main\n M README.md", "stderr": ""},
            "diff_stat": {"ok": True, "stdout": " README.md | 1 +", "stderr": ""},
        },
    )
    monkeypatch.setattr(
        support_bundle,
        "collect_doctor_output",
        lambda _project_root: {
            "ok": False,
            "returncode": 1,
            "stdout": "\n".join(
                [
                    "DeerFlow Health Check",
                    "  ✗ Node.js  (v20.19.5)",
                    "      → Node.js 22+ required. Install from https://nodejs.org/",
                    "  ✗ config.yaml found",
                    "      → Run 'make setup' to create it",
                    "Status: 2 error(s), 2 warning(s)",
                ]
            ),
            "stderr": "",
        },
    )

    output_path = tmp_path / "support.zip"
    support_bundle.create_support_bundle(
        project_root=project_root,
        out_path=output_path,
        include_doctor=True,
    )

    with zipfile.ZipFile(output_path) as zf:
        names = set(zf.namelist())

    assert {"README.md", "issue-summary.md", "ai-issue-draft.md", "triage.json"}.issubset(names)

    triage = json.loads(_zip_text(output_path, "triage.json"))
    assert triage["schema_version"] == 1
    assert triage["status"] == "needs_user_setup"
    assert triage["signals"]["config_missing"] is True
    assert triage["signals"]["node_version_too_old"] is True
    assert triage["signals"]["doctor_failed"] is True
    assert triage["signals"]["dirty_worktree"] is True
    assert triage["signals"]["extensions_config_missing"] is True
    assert "doctor_included" not in triage["active_signals"]
    assert "extensions_config_missing" not in triage["active_signals"]
    assert triage["versions"]["python"] == "3.12.11"
    assert triage["versions"]["node"] == "v20.19.5"
    assert triage["doctor"]["errors"] == 2
    assert "Run `make setup`" in triage["reporter_next_steps"][0]
    assert any("Node.js 22+" in step for step in triage["reporter_next_steps"])
    evidence_paths = [item["path"] for item in triage["evidence_files"]]
    assert "issue-summary.md" in evidence_paths
    assert "ai-issue-draft.md" in evidence_paths

    issue_summary = _zip_text(output_path, "issue-summary.md")
    assert "Triage status: needs_user_setup" in issue_summary
    assert "config_missing" in issue_summary
    assert "node_version_too_old" in issue_summary
    assert "python=3.12.11" in issue_summary
    assert "Reporter next steps" in issue_summary
    assert "Run `make setup`" in issue_summary
    assert "Attach the zip if a maintainer asks" in issue_summary
    assert "Ask the reporter to complete local setup" in issue_summary

    sidecar_summary = tmp_path / "support-issue-summary.md"
    assert sidecar_summary.exists()
    assert sidecar_summary.read_text(encoding="utf-8") == issue_summary

    issue_draft = _zip_text(output_path, "ai-issue-draft.md")
    assert "AI issue draft" in issue_draft
    assert "Do not invent if unknown" in issue_draft
    assert "Do not file this issue until every REQUIRED placeholder is replaced" in issue_draft
    assert "Issue title" in issue_draft
    assert "[bug] <REQUIRED: one-line problem summary>" in issue_draft
    assert "### Problem summary" in issue_draft
    assert "### Affected area(s)" in issue_draft
    assert "Config / setup (make, config.yaml, env)" in issue_draft
    assert "### What happened?" in issue_draft
    assert "### Expected behavior" in issue_draft
    assert "### Steps to reproduce" in issue_draft
    assert "### Relevant logs" in issue_draft
    assert "DeerFlow Health Check" in issue_draft
    assert "### How are you running DeerFlow?" in issue_draft
    assert "<REQUIRED: choose Local, Docker, CI, or Other>" in issue_draft
    assert "### Operating system" in issue_draft
    assert "macOS" in issue_draft
    assert "### Platform details" in issue_draft
    assert "arm64" in issue_draft
    assert "### Python version" in issue_draft
    assert "3.12.11" in issue_draft
    assert "### Node.js version" in issue_draft
    assert "v20.19.5" in issue_draft
    assert "### Git state" in issue_draft
    assert "branch: feat/community-support-bundle" in issue_draft
    assert "commit: abc123" in issue_draft
    assert "### Support bundle summary" in issue_draft
    assert "Triage status: needs_user_setup" in issue_draft
    assert "Attach the zip only if a maintainer asks" in issue_draft

    sidecar_draft = tmp_path / "support-issue-draft.md"
    assert sidecar_draft.exists()
    assert sidecar_draft.read_text(encoding="utf-8") == issue_draft

    bundle_readme = _zip_text(output_path, "README.md")
    assert "Start here" in bundle_readme
    assert "ai-issue-draft.md" in bundle_readme
    assert "Attach the zip if a maintainer asks" in bundle_readme


def test_triage_flags_config_parse_errors(tmp_path):
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / "config.yaml").write_text("models: [", encoding="utf-8")

    output_path = tmp_path / "support.zip"
    support_bundle.create_support_bundle(
        project_root=project_root,
        out_path=output_path,
        include_doctor=False,
    )

    triage = json.loads(_zip_text(output_path, "triage.json"))
    assert triage["status"] == "needs_user_setup"
    assert triage["signals"]["config_error"] is True
    assert "config_error" in triage["active_signals"]


def test_triage_flags_extensions_parse_errors(tmp_path):
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / "config.yaml").write_text(
        "config_version: 5\nmodels:\n  - name: default\n",
        encoding="utf-8",
    )
    (project_root / "extensions_config.json").write_text("{ broken", encoding="utf-8")

    output_path = tmp_path / "support.zip"
    support_bundle.create_support_bundle(
        project_root=project_root,
        out_path=output_path,
        include_doctor=False,
    )

    triage = json.loads(_zip_text(output_path, "triage.json"))
    assert triage["signals"]["extensions_config_error"] is True
    assert triage["status"] == "needs_user_setup"
    assert "extensions_config_error" in triage["active_signals"]
    assert any("extensions_config.json" in step for step in triage["maintainer_next_steps"])


def test_thread_summary_lists_files_without_file_contents(tmp_path):
    project_root = tmp_path / "project"
    outputs = project_root / ".deer-flow" / "threads" / "thread-123" / "user-data" / "outputs"
    uploads = project_root / ".deer-flow" / "threads" / "thread-123" / "user-data" / "uploads"
    outputs.mkdir(parents=True)
    uploads.mkdir(parents=True)
    (outputs / "report.md").write_text("raw report content with secret-content", encoding="utf-8")
    (outputs / "report-sk-live-secret.txt").write_text("filename token", encoding="utf-8")
    (uploads / "input.csv").write_text("name,value\nsecret,1\n", encoding="utf-8")

    output_path = tmp_path / "support.zip"
    support_bundle.create_support_bundle(
        project_root=project_root,
        out_path=output_path,
        thread_id="thread-123",
        include_doctor=False,
    )

    thread_summary = json.loads(_zip_text(output_path, "thread-summary.json"))
    output_names = [item["path"] for item in thread_summary["outputs"]]
    upload_names = [item["path"] for item in thread_summary["uploads"]]

    assert "report.md" in output_names
    assert "input.csv" in upload_names

    all_text = "\n".join(_zip_text(output_path, name) for name in zipfile.ZipFile(output_path).namelist())
    assert "secret-content" not in all_text
    assert "name,value" not in all_text
    assert "sk-live-secret" not in all_text
    assert "report-sk-<redacted>.txt" in all_text


def test_missing_thread_summary_does_not_leak_absolute_checked_paths(tmp_path):
    project_root = tmp_path / "project"
    project_root.mkdir()

    summary = support_bundle.collect_thread_summary(project_root, "missing-thread")

    assert summary["found"] is False
    assert summary["checked_layouts"]
    assert all(not path.startswith("/") for path in summary["checked_layouts"])
    assert all(str(tmp_path) not in path for path in summary["checked_layouts"])


def test_thread_summary_rejects_path_like_thread_id(tmp_path):
    project_root = tmp_path / "project"
    project_root.mkdir()

    with pytest.raises(ValueError, match="Invalid thread_id"):
        support_bundle.collect_thread_summary(project_root, "../outside")


@pytest.mark.parametrize("thread_id", ["..", ".", "...", "a..b", "....", "..%2f"])
def test_validate_thread_id_rejects_dot_traversal(thread_id):
    with pytest.raises(ValueError, match="Invalid thread_id"):
        support_bundle._validate_thread_id(thread_id)


def test_validate_thread_id_accepts_safe_ids():
    support_bundle._validate_thread_id("thread-123")
    support_bundle._validate_thread_id("a.b_c-1")


def test_main_reports_invalid_thread_id_without_traceback(tmp_path, capsys):
    project_root = tmp_path / "project"
    project_root.mkdir()

    exit_code = support_bundle.main(
        [
            "--project-root",
            str(project_root),
            "--out",
            str(tmp_path / "support.zip"),
            "--thread-id",
            "../outside",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "Invalid thread_id" in captured.err
    assert "Traceback" not in captured.err


def test_main_prints_reporter_next_steps_and_optional_upload(tmp_path, capsys):
    project_root = tmp_path / "project"
    project_root.mkdir()

    exit_code = support_bundle.main(
        [
            "--project-root",
            str(project_root),
            "--out",
            str(tmp_path / "support.zip"),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Issue summary:" in captured.out
    assert "Issue draft:" in captured.out
    assert "Suggested next steps:" in captured.out
    assert "If an AI assistant files the issue, start from the issue draft" in captured.out
    assert "Attach the zip if a maintainer asks" in captured.out
