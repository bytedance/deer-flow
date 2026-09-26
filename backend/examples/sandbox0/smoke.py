"""Exercise the real Sandbox0 provider without requiring an LLM credential.

Run from backend/: uv run --extra sandbox0 python examples/sandbox0/smoke.py --config /path/to/config.yaml
Only this run's new sandbox is deleted. All remote calls use the official SDK.
"""

import argparse
import json
import os
import uuid
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--output", default=".deer-flow/sandbox0-smoke")
    args = parser.parse_args()
    root = (Path(args.output) / uuid.uuid4().hex).resolve()
    root.mkdir(parents=True)
    os.environ["DEER_FLOW_HOME"] = str(root / "home")
    from deerflow.community.sandbox0 import Sandbox0Provider
    from deerflow.config.app_config import reload_app_config, set_app_config
    from deerflow.config.paths import get_paths
    from deerflow.sandbox.identity import derive_sandbox_scope_token

    skills = root / "skills" / "public" / "smoke"
    skills.mkdir(parents=True)
    (skills / "SKILL.md").write_text("---\nname: smoke\ndescription: Test remote execution.\n---\nCompute using Python.\n")
    config = reload_app_config(args.config)
    assert config.sandbox.use == "deerflow.community.sandbox0:Sandbox0Provider"
    config.sandbox.state_dir = str(root / "bindings")
    config.skills.path = str(root / "skills")
    set_app_config(config)
    thread = "smoke-" + uuid.uuid4().hex
    user = "alice"
    uploads = get_paths().sandbox_uploads_dir(thread, user_id=user)
    uploads.mkdir(parents=True)
    (uploads / "source.csv").write_text("item,value\nalpha,10\n")
    p = Sandbox0Provider()
    sid = derive_sandbox_scope_token(user_id=user, thread_id=thread)
    evidence = {"passed": False}
    try:
        sid = p.acquire(thread, user_id=user)
        s = p.get(sid)
        remote = s.remote_id
        print("provider acquired", remote, flush=True)
        assert "alpha,10" in s.read_file("/mnt/user-data/uploads/source.csv")
        assert "Compute" in s.read_file("/mnt/skills/public/smoke/SKILL.md")
        s.write_file("/mnt/user-data/workspace/hello.txt", "first\n")
        s.write_file("/mnt/user-data/workspace/hello.txt", "second\n", append=True)
        assert s.read_file("/mnt/user-data/workspace/hello.txt", 2, 2) == "second"
        s.update_file("/mnt/user-data/outputs/binary.dat", b"\x00\xfftest")
        assert s.download_file("/mnt/user-data/outputs/binary.dat") == b"\x00\xfftest"
        assert any("hello.txt" in x for x in s.list_dir("/mnt/user-data"))
        assert s.glob("/mnt/user-data", "**/*.txt")[0] == ["/mnt/user-data/workspace/hello.txt"]
        assert s.grep("/mnt/user-data", "second")[0][0].line == "second"
        assert "Exit Code: 7" in s.execute_command("exit 7")
        assert s.execute_command('printf %s "$SCOPED"', env={"SCOPED": "visible"}) == "visible"
        assert s.execute_command('printf %s "${SCOPED-unset}"') == "unset"
        s.execute_command("printf ephemeral > /tmp/deerflow-ephemeral")
        generation = p._client.sandboxes.get(remote).runtime_generation
        p.release(sid)
        print("checkpoint complete", flush=True)
        assert (get_paths().sandbox_user_data_dir(thread, user_id=user) / "outputs/binary.dat").read_bytes() == b"\x00\xfftest"
        p.shutdown()
        p = Sandbox0Provider()
        assert p.acquire(thread, user_id=user) == sid
        s = p.get(sid)
        assert s.remote_id == remote
        assert s.read_file("/mnt/user-data/workspace/hello.txt") == "first\nsecond\n"
        assert p._client.sandboxes.get(remote).runtime_generation > generation
        assert s.execute_command("test ! -e /tmp/deerflow-ephemeral && echo clean").strip() == "clean"
        p.release(sid)
        evidence = {
            "passed": True,
            "remote_id": remote,
            "checks": ["commands", "nonzero_exit", "scoped_env", "skills", "uploads", "binary_files", "line_ranges", "append", "list", "glob", "grep", "artifact_mirror", "pause_resume", "provider_restart", "ephemeral_tmp"],
        }
        print("All live provider checks passed", flush=True)
    finally:
        try:
            if sid:
                p.destroy(sid)
        finally:
            p.shutdown()
            (root / "evidence.json").write_text(json.dumps(evidence, indent=2))
            print(root / "evidence.json", flush=True)


if __name__ == "__main__":
    main()
