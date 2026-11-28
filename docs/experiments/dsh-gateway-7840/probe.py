"""Local, serial RFC experiment. Never mounted by the production Gateway."""

import asyncio
import json
import os
import shutil
import sys
from pathlib import Path

from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict

from app.gateway.authz import require_permission
from app.gateway.deps import get_thread_store
from app.gateway.routers.thread_runs import wait_run
from app.gateway.run_models import RunCreateRequest
from deerflow.utils.thread_id import ThreadId

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "dsh-headless-7840"))
from runner import reap  # noqa: E402


class Turn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prompt: str


async def headless(work, home, session, prompt):
    checkout = Path(os.environ["DSH_CHECKOUT"]).resolve()
    node = shutil.which("node")
    assert node
    args = [
        node,
        str(checkout / "apps/cli/lib/bin.js"),
        "headless",
        "--patch",
        str(HERE / "fixture.patch.yml"),
        "--json",
        "--permission-mode",
        "workspace-write",
        "--approval-policy",
        "never",
    ]
    if session:
        args.extend(["--session-id", session])
    env = {
        "HOME": str(home),
        "DSH_HOME": str(home / "dsh"),
        "PATH": os.pathsep.join([str(Path(node).parent), os.defpath]),
        "SPIKE_LLM_MODULE": (checkout / "packages/llm/llm/lib/index.js").as_uri(),
    }
    process = await asyncio.create_subprocess_exec(
        *args,
        "-",
        cwd=work,
        env=env,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(prompt.encode()), timeout=45
        )
    finally:
        await reap(process)
    if process.returncode:
        raise RuntimeError((stdout + stderr)[-3000:].decode(errors="replace"))
    frames = [json.loads(line) for line in stdout.splitlines()]
    (opened,) = (f["sessionId"] for f in frames if f["type"] == "session")
    final = frames[-1]
    if (
        final["type"] != "final"
        or final["reason"]["kind"] != "completed"
        or final["sessionId"] != opened
        or (session and opened != session)
    ):
        raise RuntimeError(f"Unexpected DSH completion: {final}")
    return process.pid, opened, final["text"], frames


def install_probe(app, work, root):
    # Each turn spawns a new process. The single Gateway retains just the opaque
    # session IDs. A production binding would need durable, owner-scoped storage.
    bindings = {}
    observations = []

    @app.post("/api/experiment/threads/{thread_id}/turn")
    @require_permission("runs", "create", owner_check=True, require_existing=True)
    async def turn(thread_id: ThreadId, body: Turn, request: Request):
        row = await get_thread_store(request).get(thread_id)
        if row is None:
            raise HTTPException(404)
        if row["assistant_id"] != "dsh-coding":
            native = RunCreateRequest(
                assistant_id=row["assistant_id"],
                input={"messages": [{"role": "user", "content": body.prompt}]},
            )
            return await wait_run(thread_id=thread_id, body=native, request=request)
        # The fixture intentionally uses the same toy worktree across probes, so a
        # clean DSH session is a strong negative control for history-only recall.
        incarnation = row["incarnation"]
        home = root / incarnation
        home.mkdir(exist_ok=True)
        pid, session, answer, frames = await headless(
            work, home, bindings.get(incarnation), body.prompt
        )
        bindings[incarnation] = session
        observations.append((thread_id, pid, session, frames))
        return {"answer": answer}

    return observations
