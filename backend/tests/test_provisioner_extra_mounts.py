"""Tests for extra_mounts support in the K8s provisioner."""

from __future__ import annotations


class TestBuildVolumesExtraMounts:
    def test_no_extra_mounts_returns_two_volumes(self, provisioner_module):
        volumes = provisioner_module._build_volumes("thread-1", extra_mounts=None)
        assert len(volumes) == 2

    def test_extra_mounts_appended(self, provisioner_module):
        mount = provisioner_module.ExtraMount(host_path="/data", container_path="/mnt/data", read_only=False)
        volumes = provisioner_module._build_volumes("thread-1", extra_mounts=[mount])
        assert len(volumes) == 3
        extra = volumes[2]
        assert extra.name == "extra-0"
        assert extra.host_path.path == "/data"
        assert extra.host_path.type == "DirectoryOrCreate"

    def test_multiple_extra_mounts(self, provisioner_module):
        mounts = [
            provisioner_module.ExtraMount(host_path="/a", container_path="/mnt/a", read_only=False),
            provisioner_module.ExtraMount(host_path="/b", container_path="/mnt/b", read_only=True),
        ]
        volumes = provisioner_module._build_volumes("thread-1", extra_mounts=mounts)
        assert len(volumes) == 4
        assert volumes[2].name == "extra-0"
        assert volumes[3].name == "extra-1"


class TestBuildVolumeMountsExtraMounts:
    def test_no_extra_mounts_returns_two_mounts(self, provisioner_module):
        mounts = provisioner_module._build_volume_mounts("thread-1", extra_mounts=None)
        assert len(mounts) == 2

    def test_extra_mount_appended_with_correct_path(self, provisioner_module):
        extra = provisioner_module.ExtraMount(host_path="/data", container_path="/mnt/data", read_only=False)
        mounts = provisioner_module._build_volume_mounts("thread-1", extra_mounts=[extra])
        assert len(mounts) == 3
        m = mounts[2]
        assert m.name == "extra-0"
        assert m.mount_path == "/mnt/data"
        assert m.read_only is False

    def test_extra_mount_read_only_flag(self, provisioner_module):
        extra = provisioner_module.ExtraMount(host_path="/ro", container_path="/mnt/ro", read_only=True)
        mounts = provisioner_module._build_volume_mounts("thread-1", extra_mounts=[extra])
        assert mounts[2].read_only is True

    def test_multiple_extra_mounts_indexed(self, provisioner_module):
        extras = [
            provisioner_module.ExtraMount(host_path="/x", container_path="/mnt/x", read_only=False),
            provisioner_module.ExtraMount(host_path="/y", container_path="/mnt/y", read_only=True),
        ]
        mounts = provisioner_module._build_volume_mounts("thread-1", extra_mounts=extras)
        assert len(mounts) == 4
        assert mounts[2].name == "extra-0"
        assert mounts[3].name == "extra-1"


class TestCreateSandboxRequestExtraMounts:
    def test_extra_mounts_optional(self, provisioner_module):
        req = provisioner_module.CreateSandboxRequest(sandbox_id="s1", thread_id="thread-1")
        assert req.extra_mounts is None

    def test_extra_mounts_parsed(self, provisioner_module):
        req = provisioner_module.CreateSandboxRequest(
            sandbox_id="s1",
            thread_id="thread-1",
            extra_mounts=[{"host_path": "/data", "container_path": "/mnt/data", "read_only": True}],
        )
        assert len(req.extra_mounts) == 1
        assert req.extra_mounts[0].host_path == "/data"
        assert req.extra_mounts[0].read_only is True
