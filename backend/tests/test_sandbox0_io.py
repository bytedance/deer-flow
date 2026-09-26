"""Exercise guest shell commands locally without credentials or a cloud runtime."""

import os
import shlex
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from deerflow.community.sandbox0 import Sandbox0Provider
from deerflow.community.sandbox0.sandbox import Sandbox0Sandbox


@pytest.mark.parametrize("operation", ["glob", "grep"])
@pytest.mark.parametrize("count,truncated", [(4, False), (5, False), (6, True)])
def test_search_only_reports_truncation_after_an_extra_match(operation, count, truncated):
    sandbox = Sandbox0Sandbox("scope", Mock(id="remote"))
    lines = [f"/workspace/f{i}.txt" if operation == "glob" else f"/workspace/f.txt:{i + 1}:hit" for i in range(count)]
    sandbox._run = Mock(return_value=SimpleNamespace(stdout="\n".join(lines) + "\n\n__DF_SEARCH_STATUS__:0\n"))
    matches, actual = getattr(sandbox, operation)("/workspace", "*.txt" if operation == "glob" else "hit", max_results=5)
    assert len(matches) == min(count, 5)
    assert actual is truncated


@pytest.mark.parametrize("operation", ["glob", "grep"])
def test_search_preserves_remote_truncation_after_filtering(operation):
    sandbox = Sandbox0Sandbox("scope", Mock(id="remote"))
    lines = [f"/workspace/.git/f{i}" if operation == "glob" else f"/workspace/.git/f:{i + 1}:hit" for i in range(56)]
    sandbox._run = Mock(return_value=SimpleNamespace(stdout="\n".join(lines) + "\n\n__DF_SEARCH_STATUS__:0\n"))
    matches, truncated = getattr(sandbox, operation)("/workspace", "*" if operation == "glob" else "hit", max_results=5)
    assert matches == []
    assert truncated is True


def local_run(command, **kwargs):
    result = subprocess.run(["bash", "-c", command], capture_output=True, text=True, timeout=10)
    return SimpleNamespace(stdout=result.stdout, stderr=result.stderr, exit_code=result.returncode)


@pytest.mark.skipif(os.name == "nt", reason="Guest commands require a POSIX shell")
@pytest.mark.parametrize("count,truncated", [(100, False), (101, True)])
def test_grep_single_file_reads_one_match_beyond_requested_limit(tmp_path, count, truncated):
    target = tmp_path / "matches.txt"
    target.write_text("hit\n" * count)
    sandbox = Sandbox0Sandbox("scope", Mock(id="remote"))
    sandbox._run = local_run
    matches, actual = sandbox.grep(str(target), "hit", max_results=100)
    assert len(matches) == 100
    assert actual is truncated


@pytest.mark.skipif(os.name == "nt", reason="Guest commands require a POSIX shell")
@pytest.mark.parametrize("content", ["", "second section", "汉字🙂\n'$(false)'\x00" * 30000], ids=["empty", "small", "large-unicode"])
def test_append_large_content_preserves_existing_bytes_and_cleans_staging(tmp_path, content):
    destination = tmp_path / "nested" / "report 'draft'.txt"
    destination.parent.mkdir()
    destination.write_bytes(b"existing\n")
    remote = Mock(id="remote")
    staged = {}

    def upload(path, data):
        # Route guest /tmp into the test directory; execute the actual append
        # command with that staged path, never a real global guest path.
        local = tmp_path / Path(path).name
        local.write_bytes(data)
        staged[path] = local

    def run(command, **kwargs):
        assert len(command.encode()) < 4096
        for guest, local in staged.items():
            command = command.replace(guest, str(local))
        return local_run(command)

    remote.write_file.side_effect = upload
    remote.delete_file.side_effect = lambda p: staged[p].unlink()
    sandbox = Sandbox0Sandbox("scope", remote)
    sandbox._run = run
    sandbox.write_file(str(destination), content, append=True)
    assert destination.read_bytes() == b"existing\n" + content.encode()
    assert len(staged) == 1
    assert not any(p.exists() for p in staged.values())
    remote.mkdir.assert_any_call(str(destination.parent), recursive=True)
    remote.read_file.assert_not_called()


def test_append_cleans_staging_after_command_failure():
    remote = Mock(id="remote")
    sandbox = Sandbox0Sandbox("scope", remote)
    sandbox._checked = Mock(side_effect=OSError("append failed"))
    with pytest.raises(OSError, match="append failed"):
        sandbox.write_file("/workspace/out.txt", "new section", append=True)
    remote.delete_file.assert_called_once_with(remote.write_file.call_args.args[0])


@pytest.mark.skipif(os.name == "nt", reason="Guest commands require a POSIX shell")
@pytest.mark.parametrize("missing", ["python3", "bash", "find", "grep", "base64", "/usr/bin/stat", "/usr/bin/realpath", None])
def test_bootstrap_fails_before_initialization_when_required_utility_missing(missing):
    # Simulate template inventory while executing the real bootstrap shell flow.
    prefix = f'missing={shlex.quote(missing or "")}; command() {{ [ "$2" != "$missing" ]; }}; test() {{ [ "$2" != "$missing" ]; }}; mkdir() {{ echo initialized; }}; '
    sandbox = Sandbox0Sandbox("scope", Mock(id="remote"))
    sandbox._run = lambda cmd, **kwargs: local_run(prefix + cmd)
    if missing is None:
        Sandbox0Provider._bootstrap(None, sandbox)
    else:
        with pytest.raises(OSError, match="exit code"):
            Sandbox0Provider._bootstrap(None, sandbox)
