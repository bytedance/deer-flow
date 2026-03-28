#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import pwd
import re
import shutil
import signal
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


PROCESS_LIST_LIMIT = 10
TMUX_CAPTURE_LINES = 120
LOG_TAIL_LINES = 80
STATUS_LINE_RE = re.compile(r"gpt-[\w.-]+\s+.*left.*Main", re.IGNORECASE)
RUN_SCRIPT_RE = re.compile(r"\b(run_[^/\s]+\.sh)\b")
TRAIN_RE = re.compile(r"\btrain\.py\b")
GENERIC_TMUX_LINE_PATTERNS = [
    re.compile(r"^use /skills\b", re.IGNORECASE),
    re.compile(r"^enter to resume\b", re.IGNORECASE),
    re.compile(r"^gpt-[\w.-]+\s+.*left\b", re.IGNORECASE),
    re.compile(r"^[•◦]\s*working\s*\(", re.IGNORECASE),
    re.compile(r"^[•◦]\s*waiting for background terminal\b", re.IGNORECASE),
    re.compile(r"^\(no output\)$", re.IGNORECASE),
]
JOB_PROCESS_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        r"\bcodex\b",
        r"\bcsub\b",
        r"\bcc\b",
        r"\bclaude\b",
        r"\bssh\b",
        r"\btmux\b",
        r"\bmihomo\b",
        r"\bclash\b",
        r"\blanggraph\b",
        r"\buvicorn\b",
        r"\bdeer-flow\b",
        r"\bopenclaw\b",
    ]
]


@dataclass
class ProcessInfo:
    pid: int
    ppid: int
    pgid: int
    elapsed_seconds: int
    stat: str
    cpu: str
    mem: str
    comm: str
    args: str

    @property
    def comm_lower(self) -> str:
        return self.comm.lower()

    @property
    def args_lower(self) -> str:
        return self.args.lower()


def sanitize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def run_command(args: list[str], *, timeout: int = 5) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def current_username() -> str:
    return pwd.getpwuid(os.getuid()).pw_name


def resolve_ps_user_selector(user: str) -> str:
    normalized = sanitize_text(user)
    if not normalized:
        return current_username()
    if normalized.isdigit():
        return normalized
    try:
        return pwd.getpwnam(normalized).pw_name
    except KeyError:
        home_dir = Path("/home") / normalized
        try:
            return str(home_dir.stat().st_uid)
        except FileNotFoundError:
            return normalized


def parse_ps_line(line: str) -> ProcessInfo | None:
    parts = line.strip().split(None, 8)
    if len(parts) < 9:
        return None
    try:
        return ProcessInfo(
            pid=int(parts[0]),
            ppid=int(parts[1]),
            pgid=int(parts[2]),
            elapsed_seconds=int(float(parts[3])),
            stat=parts[4],
            cpu=parts[5],
            mem=parts[6],
            comm=parts[7],
            args=parts[8],
        )
    except ValueError:
        return None


def list_user_processes(user: str) -> list[ProcessInfo]:
    if shutil.which("ps") is None:
        raise RuntimeError("系统里没有 ps，可先安装 procps。")
    selector = resolve_ps_user_selector(user)
    result = run_command(
        [
            "ps",
            "-u",
            selector,
            "-o",
            "pid=",
            "-o",
            "ppid=",
            "-o",
            "pgid=",
            "-o",
            "etimes=",
            "-o",
            "stat=",
            "-o",
            "%cpu=",
            "-o",
            "%mem=",
            "-o",
            "comm=",
            "-o",
            "args=",
        ]
    )
    if result.returncode != 0:
        raise RuntimeError(sanitize_text(result.stderr or result.stdout) or "ps 失败")
    processes = []
    for line in result.stdout.splitlines():
        proc = parse_ps_line(line)
        if proc and proc.pid != os.getpid():
            processes.append(proc)
    processes.sort(key=lambda item: (-item.elapsed_seconds, item.pid))
    return processes


def matches_keyword(proc: ProcessInfo, keyword: str) -> bool:
    normalized = sanitize_text(keyword).lower()
    if not normalized:
        return True
    return (
        str(proc.pid) == normalized
        or normalized in proc.comm_lower
        or normalized in proc.args_lower
    )


def basename_or_empty(value: str) -> str:
    return Path(value).name if value else ""


def short_path_tail(value: str, max_segments: int = 3) -> str:
    if not value:
        return ""
    parts = [part for part in str(value).split("/") if part]
    if len(parts) <= max_segments:
        return value
    return "…/" + "/".join(parts[-max_segments:])


def extract_prompt_task(text: str) -> str:
    normalized = text.strip()
    if not normalized:
        return ""
    patterns = [
        re.compile(r"用户(?:的第一条消息|新消息)[:：]\s*([\s\S]+)$", re.MULTILINE),
        re.compile(r"请只回复一句[:：]\s*([\s\S]+)$", re.MULTILINE),
    ]
    for pattern in patterns:
        match = pattern.search(normalized)
        if match and match.group(1):
            return sanitize_text(match.group(1))
    return ""


def infer_ssh_task(text: str) -> str:
    if "ssh-agent" in text:
        return ""
    port_forward = re.search(
        r"\bssh\b.*\s-N\b.*\s-L\s+(\d+):127\.0\.0\.1:(\d+)\s+([^\s]+)",
        text,
        re.IGNORECASE,
    )
    if port_forward:
        return (
            f"SSH 本地端口转发 {port_forward.group(1)} -> "
            f"{port_forward.group(3)}:{port_forward.group(2)}"
        )
    interactive = re.search(
        r"\bssh\b.*\s(?:root@)?([0-9a-zA-Z._-]+)(?:\s|$)",
        text,
        re.IGNORECASE,
    )
    if interactive:
        return f"SSH 会话 -> {interactive.group(1)}"
    return ""


def infer_training_task(text: str) -> str:
    if not TRAIN_RE.search(text):
        return ""
    config = re.search(r"--config-name(?:=|\s+)([^\s]+)", text)
    outputs_dir = re.search(r"\boutputs_dir=([^\s]+)", text)
    run_prefix = re.search(r"\brun_name_prefix=([^\s]+)", text)
    seed = re.search(r"\bseed=([^\s]+)", text)
    parts = ["训练 train.py"]
    if config:
        parts.append(f"config={config.group(1)}")
    if outputs_dir:
        parts.append(f"outputs={short_path_tail(outputs_dir.group(1))}")
    if run_prefix:
        parts.append(f"run={run_prefix.group(1)[:40]}")
    if seed:
        parts.append(f"seed={seed.group(1)[:20]}")
    return " | ".join(parts)


def infer_process_task(proc: ProcessInfo) -> str:
    args = proc.args
    if not args:
        return ""
    prompt_task = extract_prompt_task(args)
    if prompt_task:
        return prompt_task
    if "feishu-csub-rescue.cjs" in args:
        return "飞书 bridge 常驻服务"
    if "mcp-server-playwright" in args:
        return "Playwright MCP 浏览器子服务"
    if re.search(r"\bdomshell\b", args, re.IGNORECASE):
        return "DOMShell 浏览器桥 / MCP 服务"
    if re.search(r"\bcodex\b", args) and re.search(r"\bresume --all\b", args):
        return "Codex 交互恢复/等待继续（resume --all）"
    if re.search(r"\bcodex\b", args) and re.search(r"\bexec\b", args):
        return "Codex 一次性 exec 任务"
    for infer in (infer_ssh_task, infer_training_task):
        task = infer(args)
        if task:
            return task
    shell_script = RUN_SCRIPT_RE.search(args)
    if shell_script:
        return f"脚本任务 {shell_script.group(1)}"
    python_main = re.search(
        r"\bpython(?:\d+(?:\.\d+)*)?\b.*\b([A-Za-z0-9_.-]+\.py)\b",
        args,
    )
    if python_main:
        cwd = read_proc_link(proc.pid, "cwd")
        cwd_tail = f" @ {basename_or_empty(cwd)}" if cwd else ""
        return f"Python 任务 {python_main.group(1)}{cwd_tail}"
    if re.search(r"\bxvfb-run\b", args):
        return "Xvfb 隔离图形任务"
    return ""


def is_interesting_process(proc: ProcessInfo) -> bool:
    if proc.comm_lower == "ssh-agent" or "ssh-agent" in proc.args_lower:
        return False
    if "feishu-csub-rescue.cjs" in proc.args_lower:
        return False
    if infer_process_task(proc):
        return True
    return any(
        pattern.search(proc.comm) or pattern.search(proc.args)
        for pattern in JOB_PROCESS_PATTERNS
    )


def process_group_key(proc: ProcessInfo) -> int:
    return proc.pgid if proc.pgid > 1 else proc.pid


def choose_representative_process(members: list[ProcessInfo]) -> ProcessInfo:
    for proc in members:
        if proc.pid == proc.pgid:
            return proc
    return sorted(members, key=lambda item: (-item.elapsed_seconds, item.pid))[0]


def collapse_processes_by_group(
    processes: list[ProcessInfo], limit: int
) -> list[tuple[ProcessInfo, int, str]]:
    groups: dict[int, list[ProcessInfo]] = {}
    for proc in processes:
        groups.setdefault(process_group_key(proc), []).append(proc)
    collapsed = []
    for members in groups.values():
        leader = choose_representative_process(members)
        task = next((infer_process_task(item) for item in members if infer_process_task(item)), "")
        collapsed.append((leader, len(members), task))
    collapsed.sort(key=lambda item: (-item[0].elapsed_seconds, item[0].pid))
    return collapsed[:limit]


def read_proc_link(pid: int, target: str) -> str:
    try:
        return os.readlink(f"/proc/{pid}/{target}")
    except OSError:
        return ""


def resolve_readable_log_files(pid: int) -> tuple[str, str, list[str]]:
    stdout_target = read_proc_link(pid, "fd/1")
    stderr_target = read_proc_link(pid, "fd/2")
    readable = []
    for value in {stdout_target, stderr_target}:
        if (
            not value
            or value.startswith("pipe:[")
            or value.startswith("socket:[")
            or value.startswith("/dev/pts/")
            or value == "/dev/null"
        ):
            continue
        if Path(value).is_file():
            readable.append(value)
    return stdout_target, stderr_target, readable


def read_tail(path: str, lines: int = LOG_TAIL_LINES) -> str:
    result = run_command(["tail", "-n", str(lines), path], timeout=5)
    if result.returncode != 0:
        return f"(tail 失败：{sanitize_text(result.stderr or result.stdout)})"
    return result.stdout.strip() or "(空)"


def format_duration(seconds: int) -> str:
    hours, remainder = divmod(max(seconds, 0), 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h{minutes:02d}m"
    if minutes:
        return f"{minutes}m{secs:02d}s"
    return f"{secs}s"


def parse_events(lines: list[str], max_events: int = 5) -> list[str]:
    bullets = []
    for line in reversed(lines):
        stripped = normalize_event_line(line)
        if not stripped:
            continue
        bullets.append(stripped[:200])
        if len(bullets) >= max_events:
            break
    return list(reversed(bullets))


def choose_current_task(lines: list[str]) -> str:
    resume_task = infer_resume_picker_task(lines)
    if resume_task:
        return resume_task
    for line in reversed(lines):
        stripped = normalize_event_line(line)
        if not stripped:
            continue
        task = infer_text_task(stripped)
        if task:
            return task
        return stripped[:200]
    return ""


def infer_text_task(text: str) -> str:
    for infer in (infer_training_task, infer_ssh_task):
        task = infer(text)
        if task:
            return task
    script_match = RUN_SCRIPT_RE.search(text)
    if script_match:
        return f"脚本任务 {script_match.group(1)}"
    prompt_task = extract_prompt_task(text)
    if prompt_task:
        return prompt_task
    return ""


def infer_resume_picker_task(lines: list[str]) -> str:
    joined = "\n".join(lines)
    if "Resume a previous session" not in joined:
        return ""
    row_pattern = re.compile(
        r"^(?:>\s*)?(?:\d+\s+\w+\s+ago\s+){2,}(?P<branch>\S+)\s+(?P<cwd>\S+)\s+(?P<conversation>.+)$",
        re.IGNORECASE,
    )
    for line in lines:
        stripped = sanitize_text(line)
        if not stripped:
            continue
        match = row_pattern.match(stripped)
        if not match:
            continue
        cwd = match.group("cwd")
        conversation = match.group("conversation")
        branch = match.group("branch")
        parts = ["Codex 恢复选择界面"]
        if cwd:
            parts.append(f"cwd={cwd}")
        if conversation:
            parts.append(f"会话={conversation}")
        if branch and branch != "-":
            parts.append(f"branch={branch}")
        return " | ".join(parts)
    return "Codex 恢复选择界面"


def normalize_event_line(line: str) -> str:
    stripped = sanitize_text(line)
    if (
        not stripped
        or STATUS_LINE_RE.search(stripped)
        or stripped.startswith("› ")
        or stripped.startswith("│")
        or stripped.startswith("└")
        or stripped.startswith("─")
    ):
        return ""
    if any(pattern.search(stripped) for pattern in GENERIC_TMUX_LINE_PATTERNS):
        return ""
    waited_match = re.match(r"^•\s*Waited for background terminal\s*·\s*(.+)$", stripped, re.IGNORECASE)
    if waited_match:
        return f"后台等待：{waited_match.group(1)}"
    ran_match = re.match(r"^•\s*Ran\s+(.+)$", stripped, re.IGNORECASE)
    if ran_match:
        return f"执行：{ran_match.group(1)}"
    if stripped.startswith("• "):
        return stripped[2:].strip()
    if stripped.startswith("◦ "):
        return stripped[2:].strip()
    return re.sub(r"^(?:[-*]\s+|#+\s+)", "", stripped)


def run_tmux(args: list[str], socket_path: str) -> subprocess.CompletedProcess[str]:
    if shutil.which("tmux") is None:
        raise RuntimeError("系统里没有 tmux，可先安装 tmux。")
    command = ["tmux"]
    if socket_path:
        command.extend(["-S", socket_path])
    command.extend(args)
    return run_command(command, timeout=5)


def find_tmux_sessions(socket_path: str) -> list[dict[str, int | str]]:
    result = run_tmux(
        [
            "list-sessions",
            "-F",
            "#{session_name}\t#{session_windows}\t#{session_attached}\t#{session_created}",
        ],
        socket_path,
    )
    detail = sanitize_text(result.stderr or result.stdout)
    if result.returncode != 0:
        if re.search(r"no server running|failed to connect", detail, re.IGNORECASE):
            return []
        raise RuntimeError(f"tmux list-sessions 失败：{detail or 'unknown error'}")
    sessions = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        name, windows, attached, created = line.split("\t")
        sessions.append(
            {
                "name": name,
                "windows": int(windows or 0),
                "attached_count": int(attached or 0),
                "created_epoch": int(created or 0),
            }
        )
    return sessions


def capture_tmux_pane(session_name: str, socket_path: str, lines: int = TMUX_CAPTURE_LINES) -> str:
    result = run_tmux(["capture-pane", "-pt", session_name, "-S", f"-{lines}"], socket_path)
    if result.returncode != 0:
        detail = sanitize_text(result.stderr or result.stdout)
        raise RuntimeError(detail or f"tmux capture-pane 失败：{session_name}")
    return result.stdout.strip()


def infer_tmux_task(session_name: str, socket_path: str) -> str:
    try:
        meta = run_tmux(
            [
                "list-panes",
                "-t",
                session_name,
                "-F",
                "#{pane_current_command}\t#{pane_current_path}\t#{pane_title}",
            ],
            socket_path,
        )
        current_command = ""
        current_path = ""
        pane_title = ""
        if meta.returncode == 0:
            first_line = next((line for line in meta.stdout.splitlines() if line.strip()), "")
            if first_line:
                current_command, current_path, pane_title = first_line.split("\t")
        pane_text = capture_tmux_pane(session_name, socket_path)
        inferred = infer_text_task(pane_text)
        if inferred:
            return inferred
        if current_command or current_path or pane_title:
            parts = []
            if current_command:
                parts.append(current_command)
            if basename_or_empty(current_path):
                parts.append(f"@{basename_or_empty(current_path)}")
            if pane_title and pane_title != current_command:
                parts.append(f"title={pane_title}")
            return " ".join(parts)
    except Exception:
        return ""
    return ""


def summarize_target(target: str, socket_path: str) -> dict[str, object]:
    if target.startswith("tmux:"):
        session_name = target.split(":", 1)[1]
        pane_text = capture_tmux_pane(session_name, socket_path)
        lines = pane_text.splitlines()
        return {
            "source_type": "tmux",
            "current_task": choose_current_task(lines) or infer_tmux_task(session_name, socket_path) or "unknown",
            "recent_events": parse_events(lines),
        }
    if target.isdigit():
        proc = next((item for item in list_user_processes(current_username()) if item.pid == int(target)), None)
        if proc is None:
            proc = inspect_process(int(target))
        logs = []
        stdout_target, stderr_target, readable_files = resolve_readable_log_files(proc.pid)
        for file in readable_files[:2]:
            logs.extend(read_tail(file, 40).splitlines())
        events = parse_events(logs)
        current_task = infer_process_task(proc) or sanitize_text(proc.args) or "unknown"
        return {
            "source_type": "process",
            "current_task": current_task,
            "recent_events": events,
            "stdout": stdout_target,
            "stderr": stderr_target,
        }
    raise RuntimeError(f"不支持的 target：{target}")


def inspect_process(pid: int) -> ProcessInfo:
    proc_base = Path(f"/proc/{pid}")
    if not proc_base.exists():
        raise RuntimeError(f"没找到 PID={pid} 的进程。")
    cmd = ""
    try:
        cmd = proc_base.joinpath("cmdline").read_bytes().replace(b"\x00", b" ").decode().strip()
    except OSError:
        pass
    stat = ""
    comm = ""
    try:
        stat = proc_base.joinpath("stat").read_text()
        comm = proc_base.joinpath("comm").read_text().strip()
    except OSError:
        pass
    return ProcessInfo(
        pid=pid,
        ppid=0,
        pgid=pid,
        elapsed_seconds=0,
        stat=stat[:30],
        cpu="?",
        mem="?",
        comm=comm or "unknown",
        args=cmd or comm or "",
    )


def format_process_summary(proc: ProcessInfo, group_size: int = 1, task_summary: str = "") -> str:
    parts = [
        f"PID {proc.pid}",
        f"PGID {proc.pgid}",
        format_duration(proc.elapsed_seconds),
        proc.stat,
        proc.comm,
        sanitize_text(proc.args)[:120],
    ]
    if group_size > 1:
        parts.append(f"group={group_size}")
    if task_summary:
        parts.append(f"任务={task_summary[:90]}")
    return " | ".join(parts)


def format_tmux_summary(session: dict[str, int | str], task_summary: str) -> str:
    created_epoch = int(session.get("created_epoch") or 0)
    if created_epoch:
        created_text = subprocess.run(
            ["date", "-d", f"@{created_epoch}", "+%F %T"],
            check=False,
            capture_output=True,
            text=True,
        ).stdout.strip() or str(created_epoch)
    else:
        created_text = "未知时间"
    attached_count = int(session.get("attached_count") or 0)
    attach_text = f"attached x{attached_count}" if attached_count > 0 else "detached"
    suffix = f" | 任务={task_summary[:90]}" if task_summary else ""
    return (
        f"{session['name']} | windows={session['windows']} | {attach_text} | "
        f"created={created_text}{suffix}"
    )


def format_activity_summary(summary: dict[str, object]) -> str:
    lines = [f"当前任务：{summary.get('current_task') or 'unknown'}"]
    events = summary.get("recent_events") or []
    if isinstance(events, list) and events:
        lines.append("最近变更：")
        for item in events[-5:]:
            lines.append(f"- {item}")
    return "\n".join(lines)


def resolve_target(arg: str, user: str, socket_path: str) -> tuple[str, object]:
    target = sanitize_text(arg)
    if not target:
        raise RuntimeError("缺少目标。")
    tmux_match = re.match(r"^tmux:(.+)$", target, re.IGNORECASE)
    if tmux_match:
        return "tmux", sanitize_text(tmux_match.group(1))

    sessions = find_tmux_sessions(socket_path)
    if any(str(session["name"]) == target for session in sessions):
        return "tmux", target

    processes = list_user_processes(user)
    if target.isdigit():
        proc = next((item for item in processes if item.pid == int(target)), None)
        if proc is None:
            raise RuntimeError(f"没找到 PID={target} 的当前用户进程。")
        return "process", proc

    matches = [
        item for item in collapse_processes_by_group(
            [proc for proc in processes if matches_keyword(proc, target)],
            limit=6,
        )
    ]
    if not matches:
        raise RuntimeError(f"没找到匹配 “{target}” 的进程或 tmux session。")
    if len(matches) > 1:
        lines = [f"匹配 “{target}” 的进程不止一个，请改用更具体关键字或 PID。"]
        for proc, group_size, task_summary in matches:
            lines.append(f"- {format_process_summary(proc, group_size, task_summary)}")
        raise RuntimeError("\n".join(lines))
    proc, _, _ = matches[0]
    return "process", proc


def ensure_safe_to_signal(proc: ProcessInfo, protect_patterns: list[str]) -> None:
    if proc.pid == os.getpid():
        raise RuntimeError("不允许杀掉当前 process-control 进程本身。")
    for pattern in protect_patterns:
        if pattern and pattern in proc.args:
            raise RuntimeError(f"目标命中保护规则：{pattern}")


def send_signal_to_process(proc: ProcessInfo, signum: signal.Signals, protect_patterns: list[str]) -> str:
    ensure_safe_to_signal(proc, protect_patterns)
    if proc.pgid and proc.pgid > 1:
        try:
            os.killpg(proc.pgid, signum)
            return f"已向 PGID {proc.pgid} 发送 {signum.name}（命中 PID {proc.pid}）。"
        except ProcessLookupError:
            pass
    os.kill(proc.pid, signum)
    return f"已向 PID {proc.pid} 发送 {signum.name}。"


def cmd_jobs(args: argparse.Namespace) -> str:
    user = args.user or current_username()
    keyword = sanitize_text(args.keyword or "")
    lines = [f"用户：{user}"]

    try:
        sessions = [
            session
            for session in find_tmux_sessions(args.tmux_socket)
            if not keyword or keyword in str(session["name"])
        ]
        lines.append("")
        lines.append(f"tmux sessions{'（过滤）' if keyword else ''}：")
        if not sessions:
            lines.append("(无)")
        else:
            for session in sessions[: args.limit]:
                summary = summarize_target(f"tmux:{session['name']}", args.tmux_socket)
                lines.append(f"- {format_tmux_summary(session, str(summary.get('current_task') or ''))}")
                events = summary.get("recent_events") or []
                if isinstance(events, list):
                    for item in events[-2:]:
                        lines.append(f"  - {item}")
    except Exception as exc:
        lines.extend(["", f"tmux 查询失败：{exc}"])

    try:
        processes = [
            proc
            for proc in list_user_processes(user)
            if is_interesting_process(proc) and matches_keyword(proc, keyword)
        ]
        lines.append("")
        lines.append(f"候选后台进程{'（过滤）' if keyword else ''}：")
        if not processes:
            lines.append("(无)")
        else:
            for proc, group_size, task_summary in collapse_processes_by_group(processes, args.limit):
                lines.append(f"- {format_process_summary(proc, group_size, task_summary)}")
                summary = summarize_target(str(proc.pid), args.tmux_socket)
                events = summary.get("recent_events") or []
                if isinstance(events, list):
                    for item in events[-2:]:
                        lines.append(f"  - {item}")
    except Exception as exc:
        lines.extend(["", f"进程查询失败：{exc}"])

    lines.extend(
        [
            "",
            "常用后续命令：",
            "- ps <关键字>",
            "- log <pid>",
            "- log tmux:<session>",
            "- stop <pid|tmux:session>",
            "- kill <pid|tmux:session>",
        ]
    )
    return "\n".join(lines)


def cmd_ps(args: argparse.Namespace) -> str:
    user = args.user or current_username()
    keyword = sanitize_text(args.keyword or "")
    if not keyword:
        raise RuntimeError("用法：ps <关键字>")
    processes = collapse_processes_by_group(
        [proc for proc in list_user_processes(user) if matches_keyword(proc, keyword)],
        args.limit,
    )
    if not processes:
        return f"没有找到匹配 “{keyword}” 的进程。"
    lines = [f"匹配 “{keyword}” 的进程："]
    for proc, group_size, task_summary in processes:
        lines.append(f"- {format_process_summary(proc, group_size, task_summary)}")
        summary = summarize_target(str(proc.pid), args.tmux_socket)
        lines.append(f"  当前任务：{summary.get('current_task') or 'unknown'}")
        events = summary.get("recent_events") or []
        if isinstance(events, list):
            for item in events[-2:]:
                lines.append(f"  - {item}")
    return "\n".join(lines)


def cmd_tmux(args: argparse.Namespace) -> str:
    session_name = sanitize_text(args.session or "")
    if not session_name:
        sessions = find_tmux_sessions(args.tmux_socket)
        if not sessions:
            return "当前没有 tmux session。"
        lines = ["tmux sessions："]
        for session in sessions[: args.limit]:
            summary = summarize_target(f"tmux:{session['name']}", args.tmux_socket)
            lines.append(f"- {format_tmux_summary(session, str(summary.get('current_task') or ''))}")
        lines.append("")
        lines.append("查看某个 session 输出：tmux <session> 或 log tmux:<session>")
        return "\n".join(lines)

    summary = summarize_target(f"tmux:{session_name}", args.tmux_socket)
    pane_text = capture_tmux_pane(session_name, args.tmux_socket, LOG_TAIL_LINES)
    return "\n\n".join([format_activity_summary(summary), pane_text])


def cmd_history(args: argparse.Namespace) -> str:
    kind, target = resolve_target(args.target, args.user or current_username(), args.tmux_socket)
    if kind == "tmux":
        summary = summarize_target(f"tmux:{target}", args.tmux_socket)
        title = f"目标：tmux:{target}"
    else:
        proc = target
        assert isinstance(proc, ProcessInfo)
        summary = summarize_target(str(proc.pid), args.tmux_socket)
        title = f"目标：PID {proc.pid}"
    return "\n".join([title, format_activity_summary(summary)])


def cmd_log(args: argparse.Namespace) -> str:
    kind, target = resolve_target(args.target, args.user or current_username(), args.tmux_socket)
    if kind == "tmux":
        session_name = str(target)
        summary = summarize_target(f"tmux:{session_name}", args.tmux_socket)
        pane_text = capture_tmux_pane(session_name, args.tmux_socket, LOG_TAIL_LINES)
        return "\n\n".join([format_activity_summary(summary), pane_text])

    proc = target
    assert isinstance(proc, ProcessInfo)
    summary = summarize_target(str(proc.pid), args.tmux_socket)
    cwd = read_proc_link(proc.pid, "cwd") or "(不可读)"
    stdout_target, stderr_target, readable_files = resolve_readable_log_files(proc.pid)
    lines = [
        format_process_summary(proc, task_summary=str(summary.get("current_task") or "")),
        format_activity_summary(summary),
        f"cwd：{cwd}",
        f"stdout：{stdout_target or '(不可读)'}",
        f"stderr：{stderr_target or '(不可读)'}",
    ]
    if not readable_files:
        lines.extend(
            [
                "",
                "这个进程的 stdout/stderr 不是普通文件，暂时没法直接 tail。",
                "如果它跑在 tmux 里，改用 log tmux:<session>。",
            ]
        )
        return "\n".join(lines)
    for file in readable_files[:2]:
        lines.extend(["", f"--- tail {file} ---", read_tail(file, LOG_TAIL_LINES)])
    return "\n".join(lines)


def cmd_signal(args: argparse.Namespace, signum: signal.Signals) -> str:
    kind, target = resolve_target(args.target, args.user or current_username(), args.tmux_socket)
    if kind == "tmux":
        result = run_tmux(["kill-session", "-t", str(target)], args.tmux_socket)
        if result.returncode != 0:
            raise RuntimeError(sanitize_text(result.stderr or result.stdout) or "tmux kill-session 失败")
        return f"已停止 tmux session：{target}"
    proc = target
    assert isinstance(proc, ProcessInfo)
    summary = send_signal_to_process(proc, signum, args.protect_pattern or [])
    return summary + "\n" + format_process_summary(proc, task_summary=infer_process_task(proc))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect and control long-running local jobs")
    parser.add_argument("--user", default=current_username())
    parser.add_argument("--tmux-socket", default="")
    parser.add_argument("--protect-pattern", action="append", default=[])
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    jobs = subparsers.add_parser("jobs")
    jobs.add_argument("keyword", nargs="?")
    jobs.add_argument("--limit", type=int, default=PROCESS_LIST_LIMIT)

    ps_cmd = subparsers.add_parser("ps")
    ps_cmd.add_argument("keyword")
    ps_cmd.add_argument("--limit", type=int, default=PROCESS_LIST_LIMIT)

    tmux_cmd = subparsers.add_parser("tmux")
    tmux_cmd.add_argument("session", nargs="?")
    tmux_cmd.add_argument("--limit", type=int, default=PROCESS_LIST_LIMIT)

    history = subparsers.add_parser("history")
    history.add_argument("target")

    log_cmd = subparsers.add_parser("log")
    log_cmd.add_argument("target")

    stop = subparsers.add_parser("stop")
    stop.add_argument("target")

    kill_cmd = subparsers.add_parser("kill")
    kill_cmd.add_argument("target")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        if args.subcommand == "jobs":
            output = cmd_jobs(args)
        elif args.subcommand == "ps":
            output = cmd_ps(args)
        elif args.subcommand == "tmux":
            output = cmd_tmux(args)
        elif args.subcommand == "history":
            output = cmd_history(args)
        elif args.subcommand == "log":
            output = cmd_log(args)
        elif args.subcommand == "stop":
            output = cmd_signal(args, signal.SIGTERM)
        elif args.subcommand == "kill":
            output = cmd_signal(args, signal.SIGKILL)
        else:  # pragma: no cover
            raise RuntimeError(f"未知子命令：{args.subcommand}")
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
