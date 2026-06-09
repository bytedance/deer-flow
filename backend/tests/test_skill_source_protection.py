"""Tests for skill source code protection (3-layer defense).

Validates that skill script source code (.py files) and SKILL.md files
under /mnt/skills/ cannot be read or displayed through any tool path:
1. Prompt layer: safety directive injected into system prompt
2. Tool layer: read_file and bash block source access
3. Audit layer: SandboxAuditMiddleware blocks source read commands
"""

import pytest

from deerflow.agents.middlewares.sandbox_audit_middleware import _classify_command
from deerflow.sandbox.tools import (
    _is_protected_skill_source_path,
    _is_skill_source_read_command,
)


# ---------------------------------------------------------------------------
# Layer 1: Prompt injection
# ---------------------------------------------------------------------------


class TestSkillProtectionPrompt:
    def test_protection_section_present_in_prompt(self):
        from deerflow.agents.lead_agent.prompt import _build_skill_protection_section

        section = _build_skill_protection_section()
        assert "<skill_source_protection>" in section
        assert "NEVER read, display" in section
        assert ".py" in section
        assert "SKILL.md" in section
        assert "/mnt/skills/" in section

    def test_protection_section_contains_rejection_message(self):
        from deerflow.agents.lead_agent.prompt import _build_skill_protection_section

        section = _build_skill_protection_section()
        assert "Skill 脚本属于系统内部实现" in section

    def test_protection_section_allows_execution(self):
        from deerflow.agents.lead_agent.prompt import _build_skill_protection_section

        section = _build_skill_protection_section()
        assert "execute" in section.lower()

    def test_apply_prompt_template_includes_protection(self):
        from deerflow.agents.lead_agent.prompt import apply_prompt_template

        prompt = apply_prompt_template(thread_id="test-thread-123")
        assert "<skill_source_protection>" in prompt
        assert "NEVER read, display" in prompt


# ---------------------------------------------------------------------------
# Layer 2: Tool-level protection — read_file path detection
# ---------------------------------------------------------------------------


class TestProtectedSkillSourcePath:
    @pytest.mark.parametrize(
        "path",
        [
            "/mnt/skills/custom/daily-report/scripts/query_daily.py",
            "/mnt/skills/public/deep-research/scripts/research.py",
            "/mnt/skills/custom/vibration-fault-diagnosis/scripts/diagnose.py",
            "/mnt/skills/custom/daily-report/scripts/_ins_client.py",
            "/mnt/skills/public/bootstrap/scripts/init.py",
        ],
    )
    def test_python_files_blocked(self, path):
        assert _is_protected_skill_source_path(path) is True

    @pytest.mark.parametrize(
        "path",
        [
            "/mnt/skills/custom/daily-report/SKILL.md",
            "/mnt/skills/public/deep-research/SKILL.md",
            "/mnt/skills/custom/vibration-fault-diagnosis/SKILL.md",
        ],
    )
    def test_skill_md_blocked(self, path):
        assert _is_protected_skill_source_path(path) is True

    @pytest.mark.parametrize(
        "path",
        [
            "/mnt/skills/custom/daily-report/README.md",
            "/mnt/skills/custom/daily-report/report_scripts.yaml",
            "/mnt/skills/custom/daily-report/config.json",
            "/mnt/skills/public/deep-research/examples/sample.md",
            "/mnt/skills/custom/daily-report/scripts/",
        ],
    )
    def test_non_sensitive_files_allowed(self, path):
        assert _is_protected_skill_source_path(path) is False

    @pytest.mark.parametrize(
        "path",
        [
            "/mnt/user-data/workspace/script.py",
            "/mnt/user-data/uploads/SKILL.md",
            "/home/user/project/main.py",
            "/tmp/test.py",
        ],
    )
    def test_non_skill_paths_allowed(self, path):
        assert _is_protected_skill_source_path(path) is False


# ---------------------------------------------------------------------------
# Layer 2: Tool-level protection — bash command detection
# ---------------------------------------------------------------------------


class TestSkillSourceReadCommand:
    @pytest.mark.parametrize(
        "cmd",
        [
            "cat /mnt/skills/custom/daily-report/scripts/query_daily.py",
            "head -20 /mnt/skills/custom/daily-report/scripts/query_daily.py",
            "tail /mnt/skills/custom/daily-report/scripts/query_daily.py",
            "less /mnt/skills/custom/daily-report/scripts/query_daily.py",
            "more /mnt/skills/custom/daily-report/scripts/query_daily.py",
            "vim /mnt/skills/custom/daily-report/scripts/query_daily.py",
            "nano /mnt/skills/custom/daily-report/scripts/query_daily.py",
            "sed -n '1,10p' /mnt/skills/custom/daily-report/scripts/query_daily.py",
            "awk '{print}' /mnt/skills/custom/daily-report/scripts/query_daily.py",
        ],
    )
    def test_shell_read_py_blocked(self, cmd):
        assert _is_skill_source_read_command(cmd) is True

    @pytest.mark.parametrize(
        "cmd",
        [
            "cat /mnt/skills/custom/daily-report/SKILL.md",
            "head /mnt/skills/public/deep-research/SKILL.md",
            "less /mnt/skills/custom/pump-fault-diagnosis/SKILL.md",
        ],
    )
    def test_shell_read_skill_md_blocked(self, cmd):
        assert _is_skill_source_read_command(cmd) is True

    def test_python_open_blocked(self):
        cmd = """python -c "f=open('/mnt/skills/custom/daily-report/scripts/query_daily.py'); print(f.read())\""""
        assert _is_skill_source_read_command(cmd) is True

    def test_python3_open_blocked(self):
        cmd = """python3 -c "print(open('/mnt/skills/custom/daily-report/scripts/query_daily.py').read())\""""
        assert _is_skill_source_read_command(cmd) is True

    @pytest.mark.parametrize(
        "cmd",
        [
            "python /mnt/skills/custom/daily-report/scripts/query_daily.py --date 2026-06-08",
            "python3 /mnt/skills/custom/daily-report/scripts/query_daily.py --date 2026-06-08 --equipment E001",
            "python /mnt/skills/custom/pump-fault-diagnosis/scripts/run_pump_rule_diagnosis.py --config cfg.json",
        ],
    )
    def test_normal_skill_execution_allowed(self, cmd):
        assert _is_skill_source_read_command(cmd) is False

    @pytest.mark.parametrize(
        "cmd",
        [
            "ls /mnt/skills/custom/daily-report/",
            "ls -la /mnt/skills/custom/daily-report/scripts/",
        ],
    )
    def test_ls_skill_dir_allowed(self, cmd):
        assert _is_skill_source_read_command(cmd) is False

    def test_cat_non_skill_file_allowed(self):
        cmd = "cat /mnt/user-data/workspace/notes.txt"
        assert _is_skill_source_read_command(cmd) is False

    def test_cat_readme_in_skill_dir_allowed(self):
        """cat on a non-.py, non-SKILL.md file inside skills dir is allowed."""
        cmd = "cat /mnt/skills/custom/daily-report/README.md"
        assert _is_skill_source_read_command(cmd) is False

    def test_no_skills_path_in_command(self):
        cmd = "cat /etc/passwd"
        assert _is_skill_source_read_command(cmd) is False


# ---------------------------------------------------------------------------
# Layer 3: Sandbox audit middleware
# ---------------------------------------------------------------------------


class TestSandboxAuditSkillSource:
    @pytest.mark.parametrize(
        "cmd",
        [
            "cat /mnt/skills/custom/daily-report/scripts/query_daily.py",
            "head -20 /mnt/skills/custom/daily-report/scripts/query_daily.py",
            "tail /mnt/skills/custom/daily-report/scripts/query_daily.py",
            "less /mnt/skills/custom/daily-report/SKILL.md",
            "vim /mnt/skills/custom/pump-fault-diagnosis/scripts/diagnose.py",
        ],
    )
    def test_skill_source_read_blocked(self, cmd):
        assert _classify_command(cmd) == "block", f"Expected 'block' for: {cmd!r}"

    def test_python_open_blocked(self):
        cmd = """python -c "f=open('/mnt/skills/custom/daily-report/scripts/query_daily.py'); print(f.read())\""""
        assert _classify_command(cmd) == "block"

    @pytest.mark.parametrize(
        "cmd",
        [
            "python /mnt/skills/custom/daily-report/scripts/query_daily.py --date 2026-06-08",
            "python3 /mnt/skills/custom/pump-fault-diagnosis/scripts/run_pump_rule_diagnosis.py --config cfg.json",
        ],
    )
    def test_normal_execution_pass(self, cmd):
        assert _classify_command(cmd) == "pass", f"Expected 'pass' for: {cmd!r}"

    def test_ls_skill_dir_pass(self):
        assert _classify_command("ls /mnt/skills/custom/daily-report/") == "pass"
