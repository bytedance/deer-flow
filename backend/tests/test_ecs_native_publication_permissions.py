"""Regression: a native sandbox UID can read only the completed published tree."""

import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest


def test_native_publication_readable_by_nonroot_sandbox():
    if os.geteuid() != 0:
        pytest.skip("Requires the owned Linux root test container for UID transition")
    from ecs_executor.publication import WorkspacePublication
    from sqlalchemy import create_engine

    from deerflow.persistence.thread_meta.model import ThreadMetaRow

    with tempfile.TemporaryDirectory(prefix="native-publication-regression-", dir="/tmp") as temporary:
        root = Path(temporary)
        url = "sqlite:///" + str(root / "native.db")
        engine = create_engine(url)
        ThreadMetaRow.__table__.create(engine)
        with engine.begin() as connection:
            connection.execute(
                ThreadMetaRow.__table__.insert().values(
                    thread_id="thread",
                    user_id="owner",
                    incarnation="generation",
                    metadata_json={},
                )
            )
        publication = WorkspacePublication(workspace_root=root / "workspace", metadata_database_url=url)
        publication.paths.ensure_thread_dirs("thread", user_id="owner")
        outputs = publication.paths.sandbox_outputs_dir("thread", user_id="owner")
        private = root / "private-result.json"
        private.write_bytes(b"private pool result")
        private.chmod(0o600)
        ancestors = {path: stat.S_IMODE(path.stat().st_mode) for path in [root, root / "workspace", outputs]}
        job = {
            "id": "job",
            "user_id": "owner",
            "thread_id": "thread",
            "incarnation": "generation",
        }
        payload = b'{"files":[],"stdout":"native","truncated":false,"exit_code":0}'
        try:
            publication.publish(job, payload, {"nested/b.txt": b"dependency-proof"})
            # chdir before dropping privileges models the existing per-thread
            # outputs bind: the sandbox never traverses host tenant ancestors.
            child = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "import os,pathlib,json;os.chdir(" + repr(str(outputs)) + ");os.setgroups([]);os.setgid(1000);os.setuid(1000);"
                    "assert os.geteuid()==1000;"
                    "assert pathlib.Path('job/files/nested/b.txt').read_bytes()==b'dependency-proof';"
                    "assert json.loads(pathlib.Path('job/result.json').read_text())['stdout']=='native'",
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
            assert child.returncode == 0, "Non-root sandbox cannot read completed native publication"
            for path in [
                outputs / "job",
                outputs / "job/files",
                outputs / "job/files/nested",
            ]:
                assert stat.S_IMODE(path.stat().st_mode) == 0o755
            for path in [
                outputs / "job/result.json",
                outputs / "job/files/nested/b.txt",
            ]:
                assert stat.S_IMODE(path.stat().st_mode) == 0o644
            assert stat.S_IMODE(private.stat().st_mode) == 0o600
            assert {path: stat.S_IMODE(path.stat().st_mode) for path in ancestors} == ancestors
        finally:
            publication.engine.dispose()
            engine.dispose()
