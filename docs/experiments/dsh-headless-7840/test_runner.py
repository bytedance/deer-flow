"""Integration tests. Set DSH_CHECKOUT to a built DeepSeek Harness source tree."""

import asyncio
import json
import os
import secrets
import shutil
import signal
import sys
import tempfile
import time
import unittest
from pathlib import Path
from uuid import uuid4

from runner import execute


@unittest.skipUnless(
    os.name == "posix" and os.environ.get("DSH_CHECKOUT"), "Requires a POSIX host and a built DSH_CHECKOUT"
)
class HeadlessTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        checkout = Path(os.environ["DSH_CHECKOUT"]).resolve()
        cli = checkout / "apps/cli/lib/bin.js"
        model = checkout / "packages/llm/llm/lib/index.js"
        if not cli.is_file() or not model.is_file():
            self.fail("Build the pinned DSH checkout first (see README.md)")
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        self.work = self.root / "work"
        self.work.mkdir()
        state = self.root / "state"
        state.mkdir()
        home = self.root / "home"
        home.mkdir()
        node = shutil.which("node")
        self.assertIsNotNone(node)
        self.command = [
            node,
            str(cli),
            "headless",
            "--patch",
            str(Path(__file__).with_name("fixture.patch.yml").resolve()),
        ]
        self.env = {
            "PATH": os.pathsep.join([str(Path(node).parent), os.defpath]),
            "HOME": str(home),
            "DSH_HOME": str(state),
            "SPIKE_LLM_MODULE": model.as_uri(),
        }

    async def invoke(self, prompt, *, session=None, on_event=None, cancel=None, command=None, timeout=30, run_id=None):
        events = []
        run_id = run_id or str(uuid4())

        def receive(event):
            events.append(event)
            if on_event:
                on_event(event)

        start = time.monotonic()
        result = await execute(
            command or self.command,
            cwd=self.work,
            env=self.env,
            prompt=prompt,
            run_id=run_id,
            session_id=session,
            sink=receive,
            cancel=cancel or asyncio.Event(),
            timeout=timeout,
        )
        if result.pid is not None:
            with self.assertRaises(ProcessLookupError):
                os.kill(result.pid, 0)
            with self.assertRaises(ProcessLookupError):
                os.killpg(result.pid, 0)
        self.assertEqual([e["seq"] for e in events], list(range(1, len(events) + 1)))
        self.assertTrue(all(e["run_id"] == run_id for e in events))
        if os.environ.get("SPIKE_EVIDENCE"):
            print(
                json.dumps(
                    {
                        "task": prompt,
                        "status": result.status,
                        "reason": result.reason,
                        "exit": result.returncode,
                        "events": [e["kind"] for e in events],
                        "elapsed_s": round(time.monotonic() - start, 3),
                        "group_gone": True,
                    }
                ),
                flush=True,
            )
        return result, events

    async def test_read_then_resume_native_tool_history(self):
        from deerflow_extension_api import ExtensionPrincipal, ModelTool, ToolContext

        marker = "QUOTE-" + secrets.token_hex(6)
        source = self.work / "quote.txt"
        source.write_text(marker)
        # Exercise the existing extension contract with two simulated host contexts.
        sessions = {}
        observed = {}

        async def delegate(payload, context):
            key = (context.principal.user_id, context.thread_id)
            self.assertIsNotNone(context.run_id)
            result, events = await self.invoke(payload["prompt"], session=sessions.get(key), run_id=context.run_id)
            self.assertEqual(result.status, "success", (result, events))
            observed[context.run_id] = events
            sessions[key] = events[-1]["payload"]["sessionId"]
            return events[-1]["payload"]["text"]

        tool = ModelTool(
            "quote_review",
            "Review the synthetic quote.",
            {"type": "object", "properties": {"prompt": {"type": "string"}}, "required": ["prompt"]},
            delegate,
        )

        def host_turn():
            return ToolContext(ExtensionPrincipal("buyer"), {}, "quote-review", run_id=str(uuid4()))

        r1, r2 = host_turn(), host_turn()
        self.assertEqual(await tool.handler({"prompt": "Probe: read quote"}, r1), "Quote recorded.")
        first = observed[r1.run_id]
        session = first[0]["payload"]["sessionId"]
        (call,) = [e["payload"] for e in first if e["kind"] == "tool_call"]
        (reply,) = [e["payload"] for e in first if e["kind"] == "tool_result"]
        self.assertEqual(call["tool"], "read")
        self.assertEqual(call["callId"], reply["callId"])
        self.assertEqual(reply["status"], "completed")
        self.assertIn(marker, str(reply["result"]))
        self.assertEqual(first[-1]["payload"]["text"], "Quote recorded.")
        source.unlink()

        self.assertEqual(await tool.handler({"prompt": "Probe: recall quote"}, r2), marker)
        second = observed[r2.run_id]
        self.assertNotEqual(first[0]["run_id"], second[0]["run_id"])
        self.assertEqual(second[-1]["payload"]["sessionId"], session)
        self.assertEqual(second[-1]["payload"]["text"], marker)
        self.assertFalse(any(e["kind"] == "tool_call" for e in second))

        result, fresh = await self.invoke("Probe: recall quote")
        self.assertEqual(result.status, "success")
        self.assertEqual(fresh[-1]["payload"]["text"], "No quote in history.")

    async def test_model_failure(self):
        result, events = await self.invoke("Probe: fail")
        self.assertEqual((result.status, result.reason), ("error", "error"), events)
        self.assertNotEqual(result.returncode, 0)

    async def test_unknown_session(self):
        result, events = await self.invoke("Probe: recall quote", session="session-absent")
        self.assertEqual(result.status, "error", events)
        self.assertNotIn("session", [e["kind"] for e in events])

    async def test_cancel_then_reopen(self):
        cancel = asyncio.Event()

        def stop_at_step(event):
            if event["payload"].get("phase") == "step_start":
                cancel.set()

        result, events = await self.invoke("Probe: wait", on_event=stop_at_step, cancel=cancel)
        self.assertEqual((result.status, result.reason), ("interrupted", "owner_cancel"))
        session = events[0]["payload"]["sessionId"]
        (log,) = (self.root / "state" / "sessions").rglob("*.jsonl")
        before = [json.loads(line) for line in log.read_text().splitlines()]
        result, reopened = await self.invoke("Probe: recall quote", session=session)
        self.assertEqual(result.status, "success", (result, reopened))
        self.assertEqual(reopened[-1]["payload"]["sessionId"], session)
        after = [json.loads(line) for line in log.read_text().splitlines()]
        ends = [e["data"]["reason"]["kind"] for e in after if e["type"] == "turn/end"]
        before_ends = [e["data"]["reason"]["kind"] for e in before if e["type"] == "turn/end"]
        if os.environ.get("SPIKE_EVIDENCE"):
            print(json.dumps({"cancel_log_before": before_ends, "after_reopen": ends}), flush=True)
        self.assertEqual(ends, ["aborted", "completed"])

    async def test_unexpected_process_loss(self):
        result, events = await self.invoke("Probe: crash")
        self.assertEqual(result.returncode, -signal.SIGKILL, (result, events))
        self.assertEqual((result.status, result.reason), ("error", "missing_final"))

    async def test_incomplete_and_invalid_streams(self):
        for label, script, reason in [
            ("zero exit after session", 'print(\'{"type":"session","sessionId":"s"}\')', "missing_final"),
            ("truncated line", "print('{\"type\":')", "invalid_stream"),
            (
                "wrong final session",
                'print(\'{"type":"session","sessionId":"s"}\'); print(\'{"type":"final","sessionId":"other"}\')',
                "invalid_stream",
            ),
        ]:
            with self.subTest(label=label):
                result, _ = await self.invoke("unused", command=[sys.executable, "-c", script])
                self.assertEqual((result.status, result.reason), ("error", reason))

    async def test_reaps_an_inherited_pipe_holder(self):
        # Emulate a launcher that exits while its same-group helper retains stdout.
        script = (
            "import subprocess, sys\n"
            "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(20)'])\n"
            'print(\'{"type":"session","sessionId":"s","helper":%d}\' % p.pid, flush=True)\n'
        )
        result, events = await self.invoke("unused", command=[sys.executable, "-c", script], timeout=1)
        self.assertEqual(result.status, "timeout")
        with self.assertRaises(ProcessLookupError):
            os.kill(events[0]["payload"]["helper"], 0)

    async def test_timeout(self):
        result, _ = await self.invoke("Probe: wait", timeout=0.25)
        self.assertEqual(result.status, "timeout")
