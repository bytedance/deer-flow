"""Run the real DeerFlow graph against Sandbox0 and verify durable artifacts.

Run from backend/: uv run --extra sandbox0 python examples/sandbox0/demo.py --config /path/to/config.yaml
The config must select Sandbox0Provider and a real tool-calling model. No mock
model or synthetic tool responses are used. Only newly created demo sandboxes
are deleted by default; --keep preserves them until their configured hard TTL.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
import uuid
from pathlib import Path
from types import SimpleNamespace


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--output", default=".deer-flow/sandbox0-demo")
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args()
    output = Path(args.output).resolve() / uuid.uuid4().hex
    output.mkdir(parents=True)
    # Keep fixture data, provider bindings and the model config independent of
    # the operator's existing DeerFlow home and conversations.
    os.environ["DEER_FLOW_HOME"] = str(output / "home")

    import yaml
    from langgraph.checkpoint.memory import InMemorySaver

    from deerflow.client import DeerFlowClient
    from deerflow.community.sandbox0 import Sandbox0Provider
    from deerflow.runtime.user_context import reset_current_user, set_current_user
    from deerflow.sandbox.identity import derive_sandbox_scope_token
    from deerflow.sandbox.sandbox_provider import get_initialized_sandbox_provider, get_sandbox_provider, reset_sandbox_provider

    config = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    assert config["sandbox"]["use"] == "deerflow.community.sandbox0:Sandbox0Provider"
    config["sandbox"]["state_dir"] = str(output / "bindings")
    skills = output / "skills" / "public" / "sales-check"
    skills.mkdir(parents=True)
    (skills / "SKILL.md").write_text(
        "---\nname: sales-check\ndescription: Compute and independently verify sales totals from CSV files.\n---\n"
        "Read quantity and unit_price as numbers. Revenue is the sum of quantity * unit_price. "
        "Write total and units as JSON numbers. Use a subagent to independently verify the calculation.\n",
        encoding="utf-8",
    )
    config["skills"] = {"path": str(output / "skills"), "container_path": "/mnt/skills"}
    config_path = output / "config.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    config_path.chmod(0o600)
    os.environ["DEER_FLOW_CONFIG_PATH"] = str(config_path)
    thread = "s0-demo-" + uuid.uuid4().hex
    user = "sandbox0-demo"
    calls: set[str] = set()
    snapshots = []
    completed_subagents: set[str] = set()
    sid = derive_sandbox_scope_token(user_id=user, thread_id=thread)
    provider = None
    evidence = {"passed": False, "thread_id": thread, "checks": {}}

    def run_turn(client, prompt):
        nonlocal provider, sid
        for event in client.stream(prompt, thread_id=thread, user_id=user, recursion_limit=1000):
            if event.type == "messages-tuple":
                metadata = event.data.get("additional_kwargs", {})
                if metadata.get("deerflow_error_fallback"):
                    evidence["model_error"] = {key: metadata.get(key) for key in ("error_type", "error_reason")}
                    raise RuntimeError("DeerFlow reported a model error; check model credentials, balance, and provider availability")
                for call in event.data.get("tool_calls", []):
                    calls.add(call["name"])
                    print("tool:", call["name"], flush=True)
            elif event.type == "custom" and event.data.get("type") == "task_completed":
                completed_subagents.add(event.data["task_id"])
                print("subagent completed", flush=True)
            elif event.type == "end":
                print("turn complete", flush=True)
        provider = get_sandbox_provider()
        assert isinstance(provider, Sandbox0Provider)
        # Resolve the exact binding without resuming the now-paused runtime.
        binding_path = provider._binding_path(sid)
        assert binding_path.exists(), "Agent did not acquire a sandbox; the demo has not exercised the integration"
        binding = json.loads(binding_path.read_text(encoding="utf-8"))
        state = provider._client.sandboxes.get(binding["remote_id"])
        assert str(state.status) == "paused" and state.paused, "turn must commit a checkpoint and release compute"
        snapshots.append({"id": binding["remote_id"], "generation": state.runtime_generation, "status": str(state.status)})

    token = set_current_user(SimpleNamespace(id=user))
    try:
        client = DeerFlowClient(config_path=str(config_path), checkpointer=InMemorySaver(), subagent_enabled=True, thinking_enabled=False, plan_mode=True)
        with tempfile.TemporaryDirectory() as directory:
            csv = Path(directory) / "sales.csv"
            csv.write_text("item,quantity,unit_price\nalpha,2,10\nbeta,3,20\nalpha,1,10\n", encoding="utf-8")
            uploaded = client.upload_files(thread, [csv])
            assert uploaded["success"]
        run_turn(
            client,
            """Run an integration demonstration using actual tools, not simulated results.
Use write_todos to plan this task. Read /mnt/skills/public/sales-check/SKILL.md and follow it.
The uploaded input is /mnt/user-data/uploads/sales.csv. Use ls, glob and grep to inspect the input.
Copy sales.csv into /mnt/user-data/workspace/sales.csv and keep that working copy.
Use write_file to create /mnt/user-data/workspace/analyze.py that reads the working copy, and bash to run it.
Write /mnt/user-data/outputs/summary.json with keys total and units.
Create a Markdown report using write_file with heading DRAFT, read it, then use str_replace to replace DRAFT with FINAL.
Delegate an independent check to a task subagent, which must read sales.csv and write /mnt/user-data/outputs/review.json with verified=true and total.
Wait for the subagent result, inspect its output, then present summary.json, review.json and report.md with present_files.
Keep the script and input for the next turn. Do not ask questions.""",
        )
        summary, _ = client.get_artifact(thread, "mnt/user-data/outputs/summary.json")
        review, _ = client.get_artifact(thread, "mnt/user-data/outputs/review.json")
        assert json.loads(summary) == {"total": 90, "units": 6}
        assert json.loads(review)["verified"] is True and json.loads(review)["total"] == 90
        assert completed_subagents, "no delegated subagent completed successfully"
        evidence["checks"]["uploaded_csv_and_subagent_review"] = True
        report, _ = client.get_artifact(thread, "mnt/user-data/outputs/report.md")
        assert "FINAL" in report.decode() and "DRAFT" not in report.decode()
        evidence["checks"]["host_artifact_download"] = True
        reset_sandbox_provider()
        run_turn(
            client,
            """Continue the same workspace. Read the saved script and /mnt/user-data/workspace/sales.csv; do not recreate them.
Append gamma,1,7 to sales.csv using bash and run the existing analysis script again.
Update summary.json and report.md to reflect all rows and present both files.
This must use the previous turn's files after runtime pause/resume. Do not ask questions.""",
        )
        summary, _ = client.get_artifact(thread, "mnt/user-data/outputs/summary.json")
        assert json.loads(summary) == {"total": 97, "units": 7}
        assert snapshots[0]["id"] == snapshots[1]["id"]
        assert snapshots[1]["generation"] > snapshots[0]["generation"]
        evidence["checks"]["provider_restart_and_rootfs_resume"] = True
        required = {"bash", "ls", "read_file", "write_file", "str_replace", "glob", "grep", "task", "present_files", "write_todos"}
        missing = required - calls
        if missing:
            run_turn(
                client,
                "Complete the integration tool coverage by directly calling these registered tools: " + ", ".join(sorted(missing)) + ". A shell command with the same name does not count. Inspect /mnt/user-data/workspace and its files. "
                "For write_file/str_replace, use only a disposable /mnt/user-data/workspace/coverage.txt. "
                "For task, delegate a read-only verification of summary.json. For present_files, present the existing outputs. "
                "Do not change sales.csv, analyze.py, summary.json, review.json or report.md.",
            )
            summary, _ = client.get_artifact(thread, "mnt/user-data/outputs/summary.json")
            assert json.loads(summary) == {"total": 97, "units": 7}
            missing = required - calls
        assert not missing, f"model did not exercise required tools: {sorted(missing)}"
        evidence["checks"]["core_tool_coverage"] = True
        evidence["tools"] = sorted(calls)
        evidence["sandboxes"] = snapshots
        (output / "summary.json").write_bytes(summary)
        evidence["passed"] = True
    finally:
        reset_current_user(token)
        provider = get_initialized_sandbox_provider()
        try:
            if provider is not None:
                try:
                    if not args.keep:
                        provider.destroy(sid)
                finally:
                    provider.shutdown()
                evidence["cleanup_completed"] = True
        except BaseException:
            evidence["passed"] = False
            raise
        finally:
            evidence["completed_subagents"] = sorted(completed_subagents)
            evidence["tools"] = sorted(calls)
            evidence["sandboxes"] = snapshots
            (output / "evidence.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
            print("Evidence:", output / "evidence.json", flush=True)


if __name__ == "__main__":
    main()
