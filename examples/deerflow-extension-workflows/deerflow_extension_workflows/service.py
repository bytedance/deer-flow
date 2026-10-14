"""Supervised workflow service using only the public AgentRuns capability."""

import asyncio
import copy
import hashlib
import json
import logging
import os
import re
import sys
import tempfile
import time
import uuid
from pathlib import Path

from deerflow_extension_api import AgentRunError

from .store import TERMINAL, Store

NAMESPACE = "community.workflows"
FRAME = 48 * 1024
logger = logging.getLogger(__name__)


def encoded(value, limit=FRAME - 1):
    raw = json.dumps(value, ensure_ascii=True, allow_nan=False, sort_keys=True)
    if len(raw.encode("utf-8")) > limit:
        raise ValueError("JSON byte limit exceeded")
    return raw


def identity(value):
    return hashlib.sha256(encoded(value).encode()).hexdigest()


def text(value, limit):
    if not isinstance(value, str) or not value.strip() or len(value.encode("utf-8")) > limit:
        raise ValueError("Invalid text or UTF-8 byte limit")
    return value


def pending_input(messages):
    # Any unanswered human-input artifact in this one-step conversation stops the script.
    return any(isinstance(m.get("artifact"), dict) and isinstance(m["artifact"].get("human_input"), dict) and m["artifact"]["human_input"].get("kind") == "human_input_request" for m in messages if m.get("type", m.get("role")) == "tool")


def project(record, detail=True):
    result = {
        key: record[key]
        for key in (
            "id",
            "status",
            "created_at",
            "script_hash",
            "args_hash",
            "limits",
            "error",
        )
    }
    result["run_id"] = record["id"]
    if detail:
        result.update(
            script=record["script"],
            args=record["args"],
            logs=record["logs"],
            result=record.get("result"),
            steps=[{k: v for k, v in step.items() if k not in ("input", "output")} for step in record["steps"]],
        )
    encoded(result, 60 * 1024)
    return result


class Workflows:
    def __init__(self, config):
        self.config = config
        self.store = None
        self.available = False
        self.workers = {}
        self.processes = {}
        self.entries = {}
        self.launch_lock = asyncio.Lock()
        self.write_lock = asyncio.Lock()
        self.global_slots = asyncio.Semaphore(config["global_concurrency"])
        self.lockfile = None

    async def start(self, deps):
        def initialize():
            import fcntl

            path = Path(self.config["storage_path"])
            path.parent.mkdir(parents=True, exist_ok=True)
            lock = path.with_suffix(path.suffix + ".lock").open("a+b")
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                store = Store(path)
                store.interrupt_unfinished()
                return lock, store
            except BaseException:
                lock.close()
                raise

        self.lockfile, self.store = await asyncio.to_thread(initialize)
        self.available = True

    async def stop(self):
        async with self.launch_lock:
            self.available = False
            for entry in self.entries.values():
                entry["cancel"].set()
            workers = list(self.workers.values())
        if workers:
            await asyncio.gather(*workers, return_exceptions=True)
        if self.lockfile:
            await asyncio.to_thread(self.lockfile.close)
            self.lockfile = None

    async def wait_idle(self, run_id):
        worker = self.workers.get(run_id)
        if worker:
            await asyncio.shield(worker)

    def owner(self, context):
        if not self.available or context.settings.get("enabled") is not True:
            raise ValueError("Workflow service unavailable or disabled")
        return context.principal.user_id

    async def save(self, owner, record):
        async with self.write_lock:
            await asyncio.to_thread(self.store.put, owner, copy.deepcopy(record))

    async def launch(self, payload, context):
        owner = self.owner(context)
        if context.agent_runs is None:
            raise ValueError("Session-bound AgentRuns required; PAT/internal callers unsupported")
        if set(payload) - {"request_id", "script", "args"}:
            raise ValueError("Unexpected launch fields")
        script = text(payload.get("script"), 16000)
        encoded(script, 16000)
        request_id = text(payload.get("request_id"), 128)
        args = copy.deepcopy(payload.get("args", {}))
        if not isinstance(args, dict):
            raise ValueError("args must be a JSON object")
        encoded(args, 4000)
        limits = {
            k: self.config[k]
            for k in (
                "concurrency",
                "global_concurrency",
                "max_workflows",
                "max_workflows_per_owner",
                "admission_timeout_seconds",
                "max_calls",
                "timeout_seconds",
                "cpu_seconds",
                "memory_bytes",
            )
        }
        script_hash = hashlib.sha256(script.encode()).hexdigest()
        args_hash = identity(args)
        fingerprint = identity(
            {
                "script_hash": script_hash,
                "args_hash": args_hash,
                "limits": limits,
                "agents": self.config["agents"],
            }
        )
        async with self.launch_lock:
            self.owner(context)
            # Existing idempotent requests must remain readable even at capacity.
            # create() is the authoritative unique-key lookup, including old records outside list.
            record = {
                "id": uuid.uuid4().hex,
                "request_id": request_id,
                "fingerprint": fingerprint,
                "script_hash": script_hash,
                "args_hash": args_hash,
                "script": script,
                "args": args,
                "limits": limits,
                "created_at": time.time(),
                "status": "queued",
                "error": None,
                "steps": [],
                "logs": [],
                "result": None,
            }
            current = [e for e in self.entries.values() if e["owner"] == owner]
            # Capacity admission happens before persist, but matching retries bypass it.
            retry = await asyncio.to_thread(self.store.by_request, owner, request_id)
            if retry:
                if retry["fingerprint"] != fingerprint:
                    raise ValueError("request_id already used with different script or arguments")
                return {"run_id": retry["id"], "status": retry["status"]}
            if len(self.entries) >= self.config["max_workflows"] or len(current) >= self.config["max_workflows_per_owner"]:
                raise ValueError("Active workflow limit")
            record, created = await asyncio.to_thread(self.store.create, owner, record)
            entry = {
                "owner": owner,
                "record": record,
                "runs": context.agent_runs,
                "cancel": asyncio.Event(),
                "tasks": set(),
                "slots": asyncio.Semaphore(self.config["concurrency"]),
                "fault": None,
            }
            self.entries[record["id"]] = entry
            task = asyncio.create_task(self.execute(entry))
            self.workers[record["id"]] = task
            task.add_done_callback(lambda t: self.worker_finished(record["id"], t))
            return {"run_id": record["id"], "status": record["status"]}

    def worker_finished(self, run_id, task):
        self.workers.pop(run_id, None)
        self.entries.pop(run_id, None)
        if not task.cancelled() and task.exception() is not None:
            logger.error("Workflow %s supervisor failed (%s); inspect retained child records", run_id, type(task.exception()).__name__)

    async def get(self, payload, context):
        owner = self.owner(context)
        return project(await asyncio.to_thread(self.store.get, owner, text(payload.get("run_id"), 64)))

    async def list(self, payload, context):
        owner = self.owner(context)
        records = await asyncio.to_thread(self.store.list, owner)
        return {"runs": [project(r, False) for r in records], "limit": 20}

    async def cancel(self, payload, context):
        owner = self.owner(context)
        run_id = text(payload.get("run_id"), 64)
        record = await asyncio.to_thread(self.store.get, owner, run_id)
        entry = self.entries.get(run_id)
        if entry:
            entry["cancel"].set()
            if entry["record"]["status"] not in TERMINAL:
                entry["record"]["status"] = "cancelling"
            await self.save(owner, entry["record"])
        # Terminal waiting_input/restart records may still have child work to inspect;
        # this action never resumes or claims it cancelled an unknown child.
        return {"run_id": run_id, "status": "cancelling" if entry else record["status"]}

    async def delete(self, payload, context):
        owner = self.owner(context)
        run_id = text(payload.get("run_id"), 64)
        if run_id in self.entries:
            raise ValueError("Workflow is still cleaning up")
        await asyncio.to_thread(self.store.delete, owner, run_id)
        return {"deleted": True}

    async def step(self, entry, message):
        owner, record, runs = entry["owner"], entry["record"], entry["runs"]
        payload = message.get("payload")
        response = {"id": message["id"]}
        row = None
        try:
            if not isinstance(payload, dict) or set(payload) != {
                "stepId",
                "agentRef",
                "task",
            }:
                raise ValueError("agent requires stepId, agentRef, task")
            step_id = text(payload["stepId"], 80)
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", step_id):
                raise ValueError("stepId must contain ASCII letters, digits, underscores or hyphens")
            if payload["agentRef"] not in self.config["agents"]:
                raise ValueError("Agent reference not permitted by operator")
            if any(s["step_id"] == step_id for s in record["steps"]):
                raise ValueError("Step ID already used")
            if len(record["steps"]) >= self.config["max_calls"]:
                entry["fault"] = "Total Agent call limit"
                raise ValueError(entry["fault"])
            # Stable identity/input are recorded BEFORE thread creation or run admission.
            thread_id = "workflow-" + identity([record["id"], step_id])[:32]
            message_id = "workflow-" + identity([record["id"], step_id, 1])[:32]
            input = {
                "messages": [
                    {
                        "role": "user",
                        "id": message_id,
                        "content": encoded(payload["task"], 8000),
                    }
                ]
            }
            row = {
                "step_id": step_id,
                "attempt": 1,
                "agent_ref": payload["agentRef"],
                "thread_id": thread_id,
                "run_id": None,
                "status": "queued",
                "input": input,
                "idempotency_key": f"{record['id']}:{message_id}:1",
            }
            record["steps"].append(row)
            await self.save(owner, record)
            async with entry["slots"], self.global_slots:
                if entry["cancel"].is_set() or entry["fault"]:
                    row["status"] = "cancelled"
                    raise ValueError("Workflow stopping")
                row["status"] = "creating_thread"
                await self.save(owner, record)
                # Never cancel these awaits just because a workflow cancel was requested.
                # Keep tracking the response so an admitted child cannot disappear.
                async with asyncio.timeout(self.config["admission_timeout_seconds"]):
                    await runs.create_thread(
                        assistant_id=payload["agentRef"],
                        thread_id=thread_id,
                        metadata={"title": f"Workflow {record['id'][:8]} / {step_id}"},
                    )
                    if entry["cancel"].is_set():
                        row["status"] = "cancelled"
                        raise ValueError("Workflow stopping")
                    row["status"] = "admitting"
                    await self.save(owner, record)
                    run = await runs.start(
                        thread_id=thread_id,
                        input=input,
                        idempotency_key=row["idempotency_key"],
                    )
                row.update(run_id=run.run_id, status="running", effective_assistant_id=run.assistant_id)
                await self.save(owner, record)
                while True:
                    if entry["cancel"].is_set() or entry["fault"]:
                        await self.cancel_child(runs, row)
                        raise ValueError("Workflow stopping")
                    async with asyncio.timeout(5):
                        run = await runs.get(thread_id=thread_id, run_id=run.run_id)
                    if run.status not in ("pending", "running"):
                        break
                    await asyncio.sleep(0.02)
                row.update(child_status=run.status, stop_reason=run.stop_reason)
                async with asyncio.timeout(5):
                    state = await runs.get_state(thread_id=thread_id)
                messages = state.get("values", {}).get("messages", [])
                if state.get("next") or state.get("interrupts") or pending_input(messages):
                    row["status"] = "waiting_input"
                    entry["fault"] = "waiting_input"
                    raise ValueError("Child requires input; Phase 1 cannot resume or approve")
                if run.status != "success":
                    row["status"] = "failed"
                    raise ValueError("Agent run did not succeed")
                marker = next(
                    (i for i, m in enumerate(messages) if m.get("id") == message_id or (m.get("type", m.get("role")) in ("human", "user") and m.get("additional_kwargs", {}).get("run_id") == run.run_id)),
                    None,
                )
                if marker is None or any(m.get("type", m.get("role")) in ("human", "user") for m in messages[marker + 1 :]):
                    row["status"] = "result_conflict"
                    raise ValueError("Thread advanced before result collection")
                answers = [m for m in messages[marker + 1 :] if m.get("type", m.get("role")) in ("ai", "assistant") and not m.get("tool_calls")]
                if not answers:
                    raise ValueError("Agent completed without an answer")
                content = answers[-1].get("content")
                if isinstance(content, str):
                    try:
                        output = json.loads(content)
                    except ValueError:
                        output = content
                else:
                    output = content
                encoded(output, 12000)
                # Capture before any later turn can alter the thread checkpoint.
                row.update(status="completed", output=copy.deepcopy(output))
                response["value"] = {
                    "output": output,
                    "threadId": thread_id,
                    "runId": run.run_id,
                    "status": "success",
                }
        except TimeoutError:
            if row:
                row["status"] = "needs_reconciliation"
            entry["fault"] = "Admission timed out; inspect the stable child thread, do not replay"
            response["error"] = entry["fault"]
        except AgentRunError as exc:
            if row:
                row["status"] = "failed" if exc.status_code in (400, 403, 404, 409, 422) else "needs_reconciliation"
            response["error"] = f"AgentRuns rejected operation ({exc.status_code})"
            entry["fault"] = response["error"]
        except Exception as exc:
            if row and row["status"] in ("creating_thread", "admitting"):
                row["status"] = "needs_reconciliation"
                entry["fault"] = "Uncertain admission; inspect the child thread, do not replay"
            elif row and row["status"] == "running":
                row["status"] = "failed"
            response["error"] = str(exc)[:240] if isinstance(exc, ValueError) else "Agent step failed"
        finally:
            if row and "error" in response:
                row["error"] = response["error"]
            await self.save(owner, record)
        return response

    async def cancel_child(self, runs, row):
        try:
            async with asyncio.timeout(5):
                run = await runs.get(thread_id=row["thread_id"], run_id=row["run_id"])
                if run.status in ("pending", "running"):
                    await runs.cancel(thread_id=row["thread_id"], run_id=row["run_id"])
                    run = await runs.wait(thread_id=row["thread_id"], run_id=row["run_id"], timeout=4)
                row["child_status"] = run.status
                if row["status"] == "running":
                    row["status"] = "cancelled"
        except Exception:
            row["status"] = "needs_reconciliation"

    async def execute(self, entry):
        owner, record, runs = entry["owner"], entry["record"], entry["runs"]
        process = None
        workspace = None
        try:
            record["status"] = "running"
            await self.save(owner, record)
            workspace = await asyncio.to_thread(tempfile.TemporaryDirectory, prefix="deerflow-workflow-")
            directory = workspace.name
            # -I excludes cwd/PYTHONPATH and the environment contains no host credentials.
            env = {"PATH": os.defpath, "LANG": "C.UTF-8"}
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-I",
                str(Path(__file__).with_name("worker.py")),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                cwd=directory,
                env=env,
                limit=FRAME,
            )
            self.processes[record["id"]] = process
            await self.send(
                process,
                {
                    "script": record["script"],
                    "args": record["args"],
                    "cpu_seconds": self.config["cpu_seconds"],
                    "memory_bytes": self.config["memory_bytes"],
                },
            )
            async with asyncio.timeout(self.config["timeout_seconds"]):
                turns = 0
                while True:
                    if entry["cancel"].is_set() or entry["fault"]:
                        raise ValueError(entry["fault"] or "Cancelled")
                    turns += 1
                    if turns > 10000:
                        raise ValueError("Worker turn limit")
                    raw = await process.stdout.readline()
                    if not raw or len(raw) > FRAME:
                        raise ValueError("Worker exited or exceeded frame limit")
                    if entry["cancel"].is_set() or entry["fault"]:
                        raise ValueError(entry["fault"] or "Cancelled")
                    frame = json.loads(raw)
                    messages = frame["messages"]
                    if not isinstance(messages, list) or len(messages) > 64:
                        raise ValueError("Worker message limit")
                    for message in messages:
                        if message.get("type") == "log":
                            if len(record["logs"]) >= 20:
                                raise ValueError("Log limit")
                            log = text(message.get("text"), 160)
                            encoded(log, 160)
                            record["logs"].append(log)
                            await self.save(owner, record)
                        elif message.get("type") == "agent":
                            if type(message.get("id")) is not int or len(entry["tasks"]) >= self.config["max_calls"]:
                                raise ValueError("Pending Agent call limit")
                            entry["tasks"].add(asyncio.create_task(self.step(entry, message)))
                        else:
                            raise ValueError("Unsupported worker message")
                    if frame["outcome"] is not None:
                        outcome = frame["outcome"]
                        if entry["tasks"]:
                            raise ValueError("Script returned before awaiting Agent calls")
                        if outcome.get("type") != "result":
                            message = outcome.get("message")
                            raise ValueError(message[:240] if isinstance(message, str) else "Script failed or exceeded limits")
                        encoded(outcome["value"], 12000)
                        record.update(status="completed", result=outcome["value"])
                        break
                    # Poll the supervisor while a response is pending; do not block cancel on a child.
                    if entry["tasks"]:
                        await asyncio.wait(
                            entry["tasks"],
                            timeout=0.02,
                            return_when=asyncio.FIRST_COMPLETED,
                        )
                    else:
                        await asyncio.sleep(0.002)
                    finished = [t for t in entry["tasks"] if t.done()]
                    responses = [t.result() for t in finished]
                    entry["tasks"].difference_update(finished)
                    await self.send(process, {"responses": responses})
        except asyncio.CancelledError:
            entry["cancel"].set()
            record.update(status="interrupted", error="Host interrupted; child cleanup required")
        except Exception as exc:
            record.update(
                status="cancelled" if entry["cancel"].is_set() else "waiting_input" if entry["fault"] == "waiting_input" else "failed",
                error="Execution deadline exceeded" if isinstance(exc, TimeoutError) else str(exc)[:240],
            )
        finally:
            entry["cancel"].set()
            if process:
                if process.returncode is None:
                    try:
                        process.kill()
                    except ProcessLookupError:
                        pass
                await process.wait()
            self.processes.pop(record["id"], None)
            if workspace:
                await asyncio.to_thread(workspace.cleanup)
            # Admission tasks run to a bounded completion; no lost response on workflow cancel.
            if entry["tasks"]:
                await asyncio.gather(*entry["tasks"], return_exceptions=True)
            cleanup = [self.cancel_child(runs, row) for row in record["steps"] if row.get("run_id") and row["status"] not in ("completed", "waiting_input", "cancelled")]
            if cleanup:
                await asyncio.gather(*cleanup)
            if any(s["status"] == "needs_reconciliation" for s in record["steps"]):
                record.update(
                    status="needs_reconciliation",
                    error="Some child outcomes are uncertain; inspect their threads/runs before new work",
                )
            await self.save(owner, record)
            self.entries.pop(record["id"], None)

    async def send(self, process, message):
        process.stdin.write((encoded(message) + "\n").encode())
        await process.stdin.drain()
