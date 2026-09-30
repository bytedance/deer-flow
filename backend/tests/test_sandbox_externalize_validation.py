"""A truncated sandbox write must not be handed to the model as a readable file."""

from deerflow.agents.middlewares import tool_output_budget_middleware as mw


class _FakeSandbox:
    """Sandbox whose write_file can be told to write only part of the content."""

    def __init__(self, *, truncate: bool):
        self.truncate = truncate
        self.files: dict[str, str] = {}

    def execute_command(self, command: str) -> str:
        if command.startswith("wc -c"):
            path = command.split("<", 1)[1].strip().split()[0]
            if path not in self.files:
                return "MISSING"
            return str(len(self.files[path].encode("utf-8")))
        if command.startswith("test -s"):
            path = command.split()[2]
            return "OK" if self.files.get(path) else "MISSING"
        return ""

    def write_file(self, path: str, content: str) -> None:
        self.files[path] = content[: len(content) // 2] if self.truncate else content


def test_a_complete_write_is_accepted():
    sandbox = _FakeSandbox(truncate=False)

    path = mw._externalize_to_sandbox(
        "Z" * 100,
        tool_name="bash",
        tool_call_id="call_1",
        storage_subdir="sub",
        sandbox=sandbox,
    )

    assert path is not None


def test_a_truncated_write_is_rejected():
    """`test -s` only proves the file is non-empty, so a half-written output passed.

    The caller would then fall back to inline truncation only if we return None;
    returning a path made the model read_file a silently truncated output.
    """
    sandbox = _FakeSandbox(truncate=True)

    path = mw._externalize_to_sandbox(
        "Z" * 100,
        tool_name="bash",
        tool_call_id="call_1",
        storage_subdir="sub",
        sandbox=sandbox,
    )

    assert path is None
