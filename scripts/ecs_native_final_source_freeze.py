"""Prepare/freeze one reviewed public source bundle; never infer additional entries."""

import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import stat
import tarfile

SOURCE = Path("/Users/wenbinwang/.codex/worktrees/ecs-native-reuse/deerflow2")
ORIGINAL = Path("/private/tmp/deer-native-source-56636cebddc6.tar.gz")
ORIGINAL_SHA = "e27c3d4ce58b7f762c09386cfe1fc97464c5df639dc2d855332713915e3fa34b"
INTERNAL_MANIFEST = "native-source-entry-manifest.json"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def safe_name(name):
    p = PurePosixPath(name)
    assert name == p.as_posix() and not p.is_absolute()
    assert name and ".." not in p.parts and "\\" not in name
    assert not set(p.parts) & {
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        "node_modules",
        "private",
    }
    assert not any(x == ".env" or x.startswith(".env.") for x in p.parts)
    assert p.name not in {
        "config.yaml",
        "extensions_config.json",
        "native.json",
        "central.json",
        "worker.json",
    } or name in {"examples/ecs-native/central.json", "examples/ecs-native/worker.json"}
    assert not name.endswith((".pem", ".key", ".pyc", ".sqlite", ".db"))
    return p


def signature(info):
    return (
        info.st_dev,
        info.st_ino,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
        info.st_mode,
        info.st_uid,
        info.st_nlink,
    )


def source_bytes(name):
    relative = safe_name(name)
    assert SOURCE.is_dir() and not SOURCE.is_symlink()
    p = SOURCE
    for part in relative.parts[:-1]:
        p /= part
        assert stat.S_ISDIR(p.lstat().st_mode) and not p.is_symlink()
    p /= relative.name
    before = p.lstat()
    assert stat.S_ISREG(before.st_mode) and not p.is_symlink() and before.st_nlink == 1
    with os.fdopen(os.open(p, os.O_RDONLY | os.O_NOFOLLOW), "rb") as stream:
        assert signature(os.fstat(stream.fileno())) == signature(before)
        data = stream.read()
        assert signature(os.fstat(stream.fileno())) == signature(before)
    assert signature(p.lstat()) == signature(before) and len(data) == before.st_size
    return data, 0o755 if before.st_mode & 0o111 else 0o644


def original_names():
    assert ORIGINAL.is_file() and not ORIGINAL.is_symlink()
    data = ORIGINAL.read_bytes()
    assert digest(data) == ORIGINAL_SHA
    names = set()
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        for member in archive:
            safe_name(member.name)
            assert member.isfile() and not member.islnk() and not member.issym()
            assert member.name not in names
            names.add(member.name)
    assert len(names) == 3799 and INTERNAL_MANIFEST not in names
    return names


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["plan", "freeze"])
    parser.add_argument("--additions", type=Path, required=True)
    parser.add_argument("--additions-sha256", required=True)
    parser.add_argument("--output-directory", type=Path, default=Path("/private/tmp"))
    args = parser.parse_args()
    additions_bytes = args.additions.read_bytes()
    assert digest(additions_bytes) == args.additions_sha256
    additions = json.loads(additions_bytes)
    assert (
        additions["scope"] == "reviewed_public_source_additions"
        and additions["ops_status"] == "accepted"
    )
    assert set(additions) == {"scope", "ops_status", "files"}
    names = original_names()
    extra = additions["files"]
    assert (
        isinstance(extra, dict)
        and not set(extra) & names
        and INTERNAL_MANIFEST not in extra
    )
    rows = {}
    contents = {}
    for name in sorted(names | set(extra)):
        data, mode = source_bytes(name)
        hashed = digest(data)
        if name in extra:
            assert hashed == extra[name], "Reviewed addition changed: " + name
        rows[name] = {"sha256": hashed, "bytes": len(data), "mode": mode}
        contents[name] = data
    source_sha = digest(
        "\n".join(name + ":" + rows[name]["sha256"] for name in sorted(rows)).encode()
    )
    manifest = {
        "schema": 1,
        "original_archive_sha256": ORIGINAL_SHA,
        "original_entries": 3799,
        "additions_manifest_sha256": args.additions_sha256,
        "source_sha256": source_sha,
        "files": rows,
    }
    manifest_bytes = (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode()
    result = {
        "action": args.action,
        "source_sha256": source_sha,
        "entries": len(rows) + 1,
        "entry_manifest_sha256": digest(manifest_bytes),
        "additional_entries": sorted(extra),
    }
    if args.action == "freeze":
        directory = args.output_directory
        assert directory.is_dir() and not directory.is_symlink()
        output = directory / ("deer-native-final-source-" + source_sha[:12] + ".tar.gz")
        fd = os.open(
            output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
        )
        with os.fdopen(fd, "wb") as raw:
            with gzip.GzipFile(
                fileobj=raw, mode="wb", filename="", mtime=0
            ) as compressed:
                with tarfile.open(
                    fileobj=compressed, mode="w", format=tarfile.USTAR_FORMAT
                ) as archive:
                    for name in sorted(contents):
                        info = tarfile.TarInfo(name)
                        info.mode = rows[name]["mode"]
                        info.size = len(contents[name])
                        archive.addfile(info, io.BytesIO(contents[name]))
                    info = tarfile.TarInfo(INTERNAL_MANIFEST)
                    info.mode = 0o644
                    info.size = len(manifest_bytes)
                    archive.addfile(info, io.BytesIO(manifest_bytes))
            raw.flush()
            os.fsync(raw.fileno())
        result.update(
            archive_path=str(output),
            archive_bytes=output.stat().st_size,
            archive_sha256=digest(output.read_bytes()),
        )
        receipt = output.with_suffix("").with_suffix(".json")
        fd = os.open(
            receipt, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
        )
        with os.fdopen(fd, "w") as stream:
            json.dump(result, stream, sort_keys=True, indent=2)
            stream.write("\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
