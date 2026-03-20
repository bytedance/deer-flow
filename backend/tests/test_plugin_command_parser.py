"""Tests for plugin command markdown file parsing."""

from pathlib import Path

from src.plugins.command_parser import parse_command_file


def _write_command(commands_dir: Path, name: str, description: str = "Test", argument_hint: str = "<args>", body: str = "Command instructions.") -> Path:
    """Write a command .md file for testing."""
    commands_dir.mkdir(parents=True, exist_ok=True)
    content = f"---\ndescription: {description}\nargument-hint: \"{argument_hint}\"\n---\n\n{body}\n"
    path = commands_dir / f"{name}.md"
    path.write_text(content, encoding="utf-8")
    return path


class TestParseCommandFile:
    """Tests for parsing command .md files."""

    def test_parse_valid_command(self, tmp_path: Path):
        """Should parse a well-formed command file."""
        cmd_path = _write_command(tmp_path, "call-summary", "Summarize a call", "<transcript>", "# /call-summary\n\nProcess call notes.")

        cmd = parse_command_file(cmd_path, plugin_name="sales")

        assert cmd is not None
        assert cmd.name == "call-summary"
        assert cmd.description == "Summarize a call"
        assert cmd.argument_hint == "<transcript>"
        assert cmd.plugin_name == "sales"
        assert "Process call notes." in cmd.content

    def test_parse_command_derives_name_from_filename(self, tmp_path: Path):
        """Should derive command name from the .md filename (minus extension)."""
        cmd_path = _write_command(tmp_path, "pipeline-review", "Review pipeline")

        cmd = parse_command_file(cmd_path, plugin_name="sales")

        assert cmd is not None
        assert cmd.name == "pipeline-review"

    def test_parse_command_missing_description(self, tmp_path: Path):
        """Should return None if description is missing from frontmatter."""
        tmp_path.mkdir(exist_ok=True)
        path = tmp_path / "bad.md"
        path.write_text("---\nargument-hint: \"<x>\"\n---\n\nBody.\n", encoding="utf-8")

        cmd = parse_command_file(path, plugin_name="test")
        assert cmd is None

    def test_parse_command_no_frontmatter(self, tmp_path: Path):
        """Should return None if there is no YAML frontmatter."""
        tmp_path.mkdir(exist_ok=True)
        path = tmp_path / "nofm.md"
        path.write_text("# Just markdown\n\nNo frontmatter here.\n", encoding="utf-8")

        cmd = parse_command_file(path, plugin_name="test")
        assert cmd is None

    def test_parse_command_optional_argument_hint(self, tmp_path: Path):
        """Should default argument_hint to empty string if not provided."""
        tmp_path.mkdir(exist_ok=True)
        path = tmp_path / "simple.md"
        path.write_text("---\ndescription: Simple command\n---\n\nBody.\n", encoding="utf-8")

        cmd = parse_command_file(path, plugin_name="test")

        assert cmd is not None
        assert cmd.argument_hint == ""

    def test_parse_command_non_md_file(self, tmp_path: Path):
        """Should return None for non-.md files."""
        tmp_path.mkdir(exist_ok=True)
        path = tmp_path / "readme.txt"
        path.write_text("Not a command", encoding="utf-8")

        cmd = parse_command_file(path, plugin_name="test")
        assert cmd is None

    def test_parse_command_nonexistent_file(self, tmp_path: Path):
        """Should return None for nonexistent files."""
        cmd = parse_command_file(tmp_path / "nonexistent.md", plugin_name="test")
        assert cmd is None

    def test_parse_command_body_extraction(self, tmp_path: Path):
        """Should extract the body content after the frontmatter."""
        body = "# /forecast\n\nGenerate a sales forecast.\n\n## Steps\n1. Gather data\n2. Analyze trends"
        cmd_path = _write_command(tmp_path, "forecast", "Generate forecast", "<period>", body)

        cmd = parse_command_file(cmd_path, plugin_name="sales")

        assert cmd is not None
        assert "Generate a sales forecast." in cmd.content
        assert "## Steps" in cmd.content

    def test_parse_command_full_name(self, tmp_path: Path):
        """Should construct the full name as plugin:command."""
        cmd_path = _write_command(tmp_path, "forecast", "Forecast")

        cmd = parse_command_file(cmd_path, plugin_name="sales")

        assert cmd is not None
        assert cmd.full_name == "sales:forecast"
