"""Isolated POSIX spike for a Gateway owner supervising one DSH headless process."""

import asyncio
import json
import os
import signal
from contextlib import suppress
from dataclasses import dataclass


@dataclass(frozen=True)
class Outcome:
    status: str
    reason: str
    returncode: int | None
    pid: int | None


class StreamError(ValueError):
    pass


async def signal_group(pid, sig):
    for attempt in range(6):
        try:
            os.killpg(pid, sig)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            # Darwin can report EPERM while an exiting group is still visible.
            if sig == 0:
                return True
            if attempt == 5:
                raise
            await asyncio.sleep(0.05)


async def reap(proc):
    # A helper can retain stdout after the direct child exits.
    loop = asyncio.get_running_loop()
    for sig, grace in [(signal.SIGTERM, 6), (signal.SIGKILL, 2)]:
        if not await signal_group(proc.pid, sig):
            break
        deadline = loop.time() + grace
        while await signal_group(proc.pid, 0):
            if loop.time() >= deadline:
                if sig == signal.SIGKILL:
                    raise TimeoutError("runner group still present after SIGKILL")
                break
            await asyncio.sleep(0.05)
        else:
            break
    await proc.wait()


async def execute(command, *, cwd, env, prompt, run_id, sink, cancel, session_id=None, timeout=30):
    """command/env/cwd are trusted launch settings. sink is a local synchronous observer."""
    if cancel.is_set():
        return Outcome("interrupted", "owner_cancel", None, None)

    args = [*command, "--json", "--permission-mode", "read-only", "--approval-policy", "never"]
    if session_id is not None:
        args.extend(["--session-id", session_id])
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            "-",
            cwd=cwd,
            env=env,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True,
            limit=1024 * 1024,
        )
    except OSError:
        return Outcome("error", "spawn_failed", None, None)

    async def consume():
        seq = 0
        opened = None
        final = None
        saw_error = False
        with suppress(BrokenPipeError, ConnectionResetError):
            proc.stdin.write(prompt.encode("utf-8"))
            await proc.stdin.drain()
        proc.stdin.close()
        async for line in proc.stdout:
            event = json.loads(line)
            if not isinstance(event, dict):
                raise StreamError("invalid record")
            kind = event.get("type")
            if final is not None or saw_error:
                raise StreamError("record after terminal frame")
            if kind == "error":
                saw_error = True
            elif kind == "session":
                opened_id = event.get("sessionId")
                if opened is not None or not isinstance(opened_id, str) or not opened_id:
                    raise StreamError("invalid session")
                if session_id is not None and opened_id != session_id:
                    raise StreamError("unexpected session")
                opened = opened_id
            elif opened is None:
                raise StreamError("session missing")
            elif kind == "final":
                if event.get("sessionId") != opened:
                    raise StreamError("final belongs to another session")
                final = event
            elif kind == "thinking":
                continue
            elif kind not in ("status", "text", "tool_call", "tool_result"):
                raise StreamError("unknown frame")

            # Laboratory projection only. Tool payloads belong to this synthetic fixture.
            seq += 1
            sink(
                {"run_id": run_id, "seq": seq, "kind": kind, "payload": {k: v for k, v in event.items() if k != "type"}}
            )

        code = await proc.wait()
        if final is None:
            return ("error", "runner_error" if saw_error else "missing_final")
        reason = final.get("reason")
        kind = reason.get("kind") if isinstance(reason, dict) else None
        if code == 0 and kind == "completed":
            return "success", "completed"
        return "error", kind if isinstance(kind, str) and kind != "completed" else "invalid_completion"

    read = asyncio.create_task(consume())
    stop = asyncio.create_task(cancel.wait())
    try:
        done, _ = await asyncio.wait({read, stop}, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
        if read in done:
            try:
                status, reason = read.result()
            except ValueError:
                status, reason = "error", "invalid_stream"
        elif stop in done:
            status, reason = "interrupted", "owner_cancel"
        else:
            status, reason = "timeout", "deadline"
    finally:
        # Drain remaining bytes while stopping, including an over-limit partial record.
        read.cancel()
        stop.cancel()
        await asyncio.gather(read, stop, return_exceptions=True)

        async def drain():
            while await proc.stdout.read(65536):
                pass

        await asyncio.gather(reap(proc), drain())
    return Outcome(status, reason, proc.returncode, proc.pid)
