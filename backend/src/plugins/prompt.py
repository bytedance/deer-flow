"""Prompt generation for plugin commands."""

from .types import Command


def build_commands_prompt_section(commands: list[Command]) -> str:
    """Generate the command system prompt section with available commands.

    Returns the <command_system>...</command_system> block listing all
    available slash commands from plugins, suitable for injection into
    the agent's system prompt.

    Args:
        commands: List of Command objects to include.

    Returns:
        Formatted command system prompt section, or empty string if no commands.
    """
    if not commands:
        return ""

    command_items = "\n".join(
        f"    <command>\n"
        f"        <name>{cmd.full_name}</name>\n"
        f"        <description>{cmd.description}</description>\n"
        f"        <usage>/{cmd.full_name} {cmd.argument_hint}</usage>\n"
        f"    </command>"
        for cmd in commands
    )
    commands_list = f"<available_commands>\n{command_items}\n</available_commands>"

    return f"""<command_system>
You have access to slash commands from installed plugins. When a user invokes a command
(e.g., /sales:forecast <period>), load and follow the command's instructions.

**Command Execution Pattern:**
1. When the user invokes a slash command, find the matching command below
2. The command instructions will be injected into the conversation
3. Follow the command's workflow and instructions precisely
4. Use the user's arguments as input to the command

{commands_list}

</command_system>"""
