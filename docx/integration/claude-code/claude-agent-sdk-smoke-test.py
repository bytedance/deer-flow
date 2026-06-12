"""Claude Agent SDK smoke test.

Run from backend/.venv:
    backend/.venv/bin/python docx/integration/claude-code/claude-agent-sdk-smoke-test.py

Sends a trivial prompt "What is 2 + 2?" to the Claude Code CLI subprocess
spawned by the Python SDK. With ``cli_path`` set, the SDK reuses the system
``claude`` binary instead of the bundled one in the wheel.
"""
import anyio
from claude_agent_sdk import query, ClaudeAgentOptions

# Absolute path to the system-installed Claude Code CLI (npm global,
# @anthropic-ai/claude-code@2.1.139, via nvm node v24.14.1).
# Override this if your install lives elsewhere.
CLAUDE_PATH = "/Users/raidery/.nvm/versions/node/v24.14.1/bin/claude"


async def main():
    async for message in query(
        prompt="What is 2 + 2?",
        options=ClaudeAgentOptions(cli_path=CLAUDE_PATH),
    ):
        print(message)


if __name__ == "__main__":
    anyio.run(main)
