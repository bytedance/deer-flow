"""Slash-command registry for the DeerFlow TUI (pure).

Normalizes two command sources into one searchable list:

* **Built-ins** — TUI-owned affordances (``/help``, ``/model``, ``/threads`` …).
* **Skills** — one ``/<skill-name>`` per enabled skill, preserving DeerFlow's
  existing slash-skill activation semantics.

The picker filters this list; :func:`resolve` classifies a submitted line as a
built-in command, a skill activation, an unknown command, or a plain message.
No Textual dependency.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Command:
    name: str  # without leading slash
    description: str
    category: Literal["builtin", "skill"] = "builtin"


@dataclass(frozen=True)
class Resolution:
    kind: Literal["builtin", "skill", "unknown", "message"]
    name: str = ""
    args: str = ""
    text: str = ""


# Built-in commands, ordered for display in /help and the picker.
BUILTIN_COMMANDS: tuple[Command, ...] = (
    Command("help", "Show commands and keybindings"),
    Command("new", "Start a fresh thread"),
    Command("clear", "Clear the transcript display"),
    Command("threads", "Open the thread switcher"),
    Command("switch", "Open the thread switcher"),
    Command("resume", "Resume a thread by id or title"),
    Command("goal", "Set, show or clear the active goal"),
    Command("model", "Open the model picker"),
    Command("skills", "Browse enabled and available skills"),
    Command("tools", "Show built-in, MCP and sandbox tools"),
    Command("mcp", "Show MCP server status"),
    Command("memory", "Show memory status and injected facts"),
    Command("uploads", "Show uploaded files for this thread"),
    Command("artifacts", "Show generated artifacts"),
    Command("details", "Toggle verbose activity rendering"),
    Command("usage", "Show token usage and context"),
    Command("config", "Show resolved config paths and overrides"),
    Command("quit", "Exit the TUI"),
)

_BUILTIN_NAMES = frozenset(c.name for c in BUILTIN_COMMANDS)


def build_registry(skills: list[dict]) -> list[Command]:
    """Merge built-ins with one command per enabled skill."""
    commands = list(BUILTIN_COMMANDS)
    for skill in skills:
        if not skill.get("enabled", False):
            continue
        name = skill.get("name")
        if not name or name in _BUILTIN_NAMES:
            continue
        commands.append(Command(name=name, description=skill.get("description", "") or "", category="skill"))
    return commands


def filter_commands(commands: list[Command], query: str) -> list[Command]:
    """Filter + rank commands for the picker.

    Ranking: name-prefix matches first, then name-substring, then
    description-substring. Original order is preserved within a rank tier.
    """
    q = query.strip().lower()
    if not q:
        return commands

    prefix: list[Command] = []
    substring: list[Command] = []
    description: list[Command] = []
    for command in commands:
        name = command.name.lower()
        if name.startswith(q):
            prefix.append(command)
        elif q in name:
            substring.append(command)
        elif q in command.description.lower():
            description.append(command)
    return prefix + substring + description


def resolve(text: str, skills: list[str] | None = None) -> Resolution:
    """Classify a submitted input line."""
    stripped = text.strip()
    if not stripped.startswith("/"):
        return Resolution(kind="message", text=text)

    body = stripped[1:]
    name, _, args = body.partition(" ")
    name = name.strip()
    args = args.strip()

    if not name:
        return Resolution(kind="unknown", name="")

    if name in _BUILTIN_NAMES:
        return Resolution(kind="builtin", name=name, args=args)

    if skills and name in skills:
        return Resolution(kind="skill", name=name, args=args)

    return Resolution(kind="unknown", name=name, args=args)
