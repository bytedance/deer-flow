"""Fetch one pinned official OCI layer; select its official headless artifacts only."""

import gzip
import hashlib
import json
import os
import stat
from pathlib import PurePosixPath
import tarfile
import time
import urllib.parse
import urllib.request

INDEX = "a9731514f24121d1dcd25d58d0a38146646d290a5998fd80d3e533e7b5e21c69"
MANIFEST = "80fd7c1aad9600ea348572dd46ca00b9ea31d890831f5838fc61319ab79900d2"
LAYER = "d6767936d02bbcee2ee5e024d6e22a6edfa609a13b068b015be122a4b1f50026"
SIZE = 806539070
ETAG = '"0x8DED5C7628018C6"'
MODIFIED = "Mon, 29 Jun 2026 10:15:46 GMT"
HOSTS = {"mcr.microsoft.com", "southeastasia.data.mcr.microsoft.com"}
SELECTED = {"chromium_headless_shell-1228", "ffmpeg-1011"}


class OfficialRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urllib.parse.urlsplit(newurl)
        assert target.scheme == "https" and target.hostname in HOSTS
        assert (
            target.username is None
            and target.password is None
            and target.port in (None, 443)
        )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def opener():
    return urllib.request.build_opener(OfficialRedirect())


def metadata(client, path, expected):
    req = urllib.request.Request(
        "https://mcr.microsoft.com/v2/playwright/python/manifests/" + path,
        headers={
            "Accept": "application/vnd.docker.distribution.manifest.list.v2+json, application/vnd.docker.distribution.manifest.v2+json",
            "Accept-Encoding": "identity",
        },
    )
    with client.open(req, timeout=30) as response:
        body = response.read(65537)
        assert response.status == 200 and len(body) <= 65536
    assert hashlib.sha256(body).hexdigest() == expected
    return json.loads(body)


def prepare(work, deadline):
    client = opener()
    index = metadata(client, "v1.61.0-noble", INDEX)
    chosen = [
        x
        for x in index["manifests"]
        if x.get("platform") == {"architecture": "amd64", "os": "linux"}
    ]
    assert len(chosen) == 1 and chosen[0]["digest"] == "sha256:" + MANIFEST
    manifest = metadata(client, "sha256:" + MANIFEST, MANIFEST)
    assert any(
        x["digest"] == "sha256:" + LAYER
        and x["size"] == SIZE
        and x["mediaType"] == "application/vnd.docker.image.rootfs.diff.tar.gzip"
        for x in manifest["layers"]
    )
    archive = work.parent / "browser-mcr-1.61.0-1228/official-browser-layer.tar.gz"
    assert all(not p.is_symlink() for p in [archive, *archive.parents])
    info = archive.lstat()
    assert stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
    assert stat.S_IMODE(info.st_mode) == 0o600 and info.st_nlink == 1
    assert info.st_size == SIZE
    digest = hashlib.sha256()
    started = time.monotonic()
    with archive.open("rb") as stream:
        for block in iter(lambda: stream.read(1048576), b""):
            assert time.monotonic() < deadline
            digest.update(block)
    assert digest.hexdigest() == LAYER
    after = archive.lstat()
    stable_fields = (
        "st_dev",
        "st_ino",
        "st_size",
        "st_mtime_ns",
        "st_ctime_ns",
        "st_mode",
        "st_uid",
        "st_nlink",
    )
    assert tuple(getattr(after, field) for field in stable_fields) == tuple(
        getattr(info, field) for field in stable_fields
    ), "Cached official archive changed during verification"
    count = SIZE
    destination = work / "context/browser-artifacts"
    destination.mkdir(mode=0o755)
    total = 0
    files = 0
    discarded_validation_stamps = []
    # Never extract unselected browser families, Ubuntu libraries or link entries.
    with (
        gzip.open(archive, "rb") as compressed,
        tarfile.open(fileobj=compressed, mode="r|") as tar,
    ):
        for member in tar:
            assert time.monotonic() < deadline, (
                "Official artifact selection deadline reached"
            )
            path = PurePosixPath(member.name)
            assert not path.is_absolute() and ".." not in path.parts
            if (
                len(path.parts) < 2
                or path.parts[0] != "ms-playwright"
                or path.parts[1] not in SELECTED
            ):
                continue
            assert "\\" not in member.name
            if len(path.parts) == 3 and path.parts[2] == "DEPENDENCIES_VALIDATED":
                assert member.isfile()
                discarded_validation_stamps.append(str(path))
                continue  # Ubuntu validation is not Debian validation.
            assert member.isdir() or member.isfile()
            assert member.mode & 0o7000 == 0
            target = destination.joinpath(*path.parts[1:])
            assert not target.is_symlink() and all(
                not p.is_symlink() for p in target.parents
            )
            if member.isdir():
                target.mkdir(mode=0o755, parents=True, exist_ok=True)
                continue
            assert not target.exists() and 0 <= member.size <= 512 * 1024**2
            total += member.size
            files += 1
            assert total <= 1024**3 and files <= 5000
            target.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
            mode = 0o755 if member.mode & 0o111 else 0o644
            outfd = os.open(
                target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode
            )
            with os.fdopen(outfd, "wb") as output:
                source = tar.extractfile(member)
                copied = 0
                while True:
                    assert time.monotonic() < deadline
                    chunk = source.read(1048576)
                    if not chunk:
                        break
                    copied += len(chunk)
                    output.write(chunk)
                assert copied == member.size
        # Reach gzip EOF to validate its CRC; do not retain remaining payload bytes.
        while compressed.read(1048576):
            assert time.monotonic() < deadline
    assert {p.name for p in destination.iterdir()} == SELECTED
    tree = hashlib.sha256()
    for folder in SELECTED:
        marker = destination / folder / "INSTALLATION_COMPLETE"
        assert (
            marker.is_file() and not marker.is_symlink()
        )  # Official marker only; never synthesize one.
    for path in sorted(destination.rglob("*")):
        assert not path.is_symlink()
        if path.is_file():
            assert path.stat().st_uid == os.getuid() and path.stat().st_nlink == 1
            file_hash = hashlib.sha256()
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1048576), b""):
                    file_hash.update(block)
            value = file_hash.hexdigest()
            tree.update(
                str(path.relative_to(destination)).encode()
                + b"\0"
                + value.encode()
                + b"\0"
            )
    return {
        "official_index_sha256": INDEX,
        "official_amd64_manifest_sha256": MANIFEST,
        "layer_sha256": LAYER,
        "layer_bytes": count,
        "selected_directories": sorted(SELECTED),
        "selected_tree_sha256": tree.hexdigest(),
        "selected_files": files,
        "selected_bytes": total,
        "official_installation_markers_preserved": True,
        "source_host": "southeastasia.data.mcr.microsoft.com",
        "cached_verified_archive_reused": True,
        "cached_archive_relative_path": "browser-mcr-1.61.0-1228/official-browser-layer.tar.gz",
        "cached_hash_and_selection_seconds": round(time.monotonic() - started, 2),
        "other_browsers_or_ubuntu_libs_copied": False,
        "discarded_ubuntu_validation_stamps": discarded_validation_stamps,
    }
