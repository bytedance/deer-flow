---
name: process-supervisor
description: Inspect and control long-running local jobs, tmux sessions, and background processes with task-oriented summaries. Use when the user wants `jobs`, `ps <kw>`, `tmux`, `history`, `log`, `stop`, or `kill` style control over csub/Codex/Claude/训练脚本/SSH 转发等长期任务.
---

# Process Supervisor

Use this skill when the user needs a compact, operator-friendly view of what the machine is doing now.

It provides one shared CLI:

```bash
python3 scripts/process_control.py <subcommand> ...
```

## Subcommands

- `jobs [keyword]`
  - List tmux sessions and interesting background processes, with inferred current task and recent changes.
- `ps <keyword>`
  - Search processes by keyword or PID-like text.
- `tmux [session]`
  - List tmux sessions or show a specific session's recent pane output.
- `history <pid|tmux:session>`
  - Show the current task plus recent change history for a target.
- `log <pid|keyword|tmux:session>`
  - Show detailed info and tail output for a target.
- `stop <pid|keyword|tmux:session>`
  - Send `SIGTERM` to a process group / PID, or kill a tmux session.
- `kill <pid|keyword|tmux:session>`
  - Send `SIGKILL` to a process group / PID, or kill a tmux session.

## Important flags

- `--user <name>`
  - Process owner to inspect. Default is the current user.
- `--tmux-socket <path>`
  - Explicit tmux socket path, useful from containers that need to inspect a host user's tmux server (for example `/tmp/tmux-1000/default`).
- `--protect-pattern <substring>`
  - Refuse to stop / kill targets whose command line contains this substring.
- `--limit <n>`
  - Output cap for `jobs`, `ps`, or `tmux`.

## Typical host-side usage

```bash
python3 scripts/process_control.py jobs
python3 scripts/process_control.py ps codex
python3 scripts/process_control.py log tmux:sphere
python3 scripts/process_control.py history 3188240
python3 scripts/process_control.py stop 3188240 --protect-pattern feishu-csub-rescue.cjs
```

## Bot / agent integration patterns

This skill is intended to be the shared backend for local operator-facing chat commands.

- **Feishu csub / cc bridges**
  - map `jobs`, `ps`, `tmux`, `history`, `log`, `stop`, `kill` directly to this CLI
  - pass protect patterns so the bot cannot kill its own bridge process
- **OpenClaw**
  - expose the same commands in direct/private chat rules
  - call the workspace copy of this script and return stdout directly
- **DeerFlow**
  - intercept the same commands before normal agent routing
  - if DeerFlow runs in Docker but must inspect host jobs, run the gateway container with:
    - `pid: host`
    - host tmux socket bind mount
    - read-only bind mount for host log paths (for example `/home/leadtek`)

## Typical container-side usage for host process inspection

If the caller runs inside a container but needs to inspect host jobs:

- run in host PID namespace (`pid: host`)
- provide host tmux socket via bind mount
- mount `/home/leadtek` read-only if you want to tail host log files

Example:

```bash
python3 /app/skills/process-supervisor/scripts/process_control.py \
  --user leadtek \
  --tmux-socket /tmp/tmux-1000/default \
  jobs
```

## Output contract

The CLI returns plain text, ready to paste into Feishu/Slack/Telegram/OpenClaw replies.

Design goals:

- short summary first
- enough task detail to identify what the job is doing now
- avoid raw `ps` dumps when a task-oriented description is possible
- fail fast on ambiguous `stop/kill/log/history` targets
- prefer shared implementation over duplicating per-bot process inspection logic
