"""Regression tests for provisioner PVC volume support."""


# ── _build_volumes ─────────────────────────────────────────────────────


class TestBuildVolumes:
    """Tests for _build_volumes: PVC vs hostPath selection."""

    def test_default_uses_hostpath_for_skills(self, provisioner_module):
        """When SKILLS_PVC_NAME is empty, skills volume should use hostPath."""
        provisioner_module.SKILLS_PVC_NAME = ""
        volumes = provisioner_module._build_volumes("thread-1")
        skills_vol = volumes[0]
        assert skills_vol.host_path is not None
        assert skills_vol.host_path.path == provisioner_module.SKILLS_HOST_PATH
        assert skills_vol.host_path.type == "Directory"
        assert skills_vol.persistent_volume_claim is None

    def test_default_uses_hostpath_for_userdata(self, provisioner_module):
        """When USERDATA_PVC_NAME is empty, user-data volume should use hostPath."""
        provisioner_module.USERDATA_PVC_NAME = ""
        volumes = provisioner_module._build_volumes("thread-1")
        userdata_vol = volumes[1]
        assert userdata_vol.host_path is not None
        assert userdata_vol.persistent_volume_claim is None

    def test_hostpath_userdata_includes_thread_id(self, provisioner_module):
        """hostPath user-data path should include thread_id."""
        provisioner_module.USERDATA_PVC_NAME = ""
        volumes = provisioner_module._build_volumes("my-thread-42")
        userdata_vol = volumes[1]
        path = userdata_vol.host_path.path
        assert "my-thread-42" in path
        assert path.endswith("user-data")
        assert userdata_vol.host_path.type == "DirectoryOrCreate"

    def test_skills_pvc_overrides_hostpath(self, provisioner_module):
        """When SKILLS_PVC_NAME is set, skills volume should use PVC."""
        provisioner_module.SKILLS_PVC_NAME = "my-skills-pvc"
        volumes = provisioner_module._build_volumes("thread-1")
        skills_vol = volumes[0]
        assert skills_vol.persistent_volume_claim is not None
        assert skills_vol.persistent_volume_claim.claim_name == "my-skills-pvc"
        assert skills_vol.persistent_volume_claim.read_only is True
        assert skills_vol.host_path is None

    def test_userdata_pvc_overrides_hostpath(self, provisioner_module):
        """When USERDATA_PVC_NAME is set, user-data volume should use PVC."""
        provisioner_module.USERDATA_PVC_NAME = "my-userdata-pvc"
        volumes = provisioner_module._build_volumes("thread-1")
        userdata_vol = volumes[1]
        assert userdata_vol.persistent_volume_claim is not None
        assert userdata_vol.persistent_volume_claim.claim_name == "my-userdata-pvc"
        assert userdata_vol.host_path is None

    def test_both_pvc_set(self, provisioner_module):
        """When both PVC names are set, both volumes use PVC."""
        provisioner_module.SKILLS_PVC_NAME = "skills-pvc"
        provisioner_module.USERDATA_PVC_NAME = "userdata-pvc"
        volumes = provisioner_module._build_volumes("thread-1")
        assert volumes[0].persistent_volume_claim is not None
        assert volumes[1].persistent_volume_claim is not None

    def test_returns_two_volumes(self, provisioner_module):
        """Should always return exactly two volumes."""
        provisioner_module.SKILLS_PVC_NAME = ""
        provisioner_module.USERDATA_PVC_NAME = ""
        assert len(provisioner_module._build_volumes("t")) == 2

        provisioner_module.SKILLS_PVC_NAME = "a"
        provisioner_module.USERDATA_PVC_NAME = "b"
        assert len(provisioner_module._build_volumes("t")) == 2

    def test_volume_names_are_stable(self, provisioner_module):
        """Volume names must stay 'skills' and 'user-data'."""
        volumes = provisioner_module._build_volumes("thread-1")
        assert volumes[0].name == "skills"
        assert volumes[1].name == "user-data"


# ── _build_volume_mounts ───────────────────────────────────────────────


class TestBuildVolumeMounts:
    """Tests for _build_volume_mounts: mount paths and subPath behavior."""

    def test_default_no_subpath(self, provisioner_module):
        """hostPath mode should not set sub_path on user-data mount."""
        provisioner_module.USERDATA_PVC_NAME = ""
        mounts = provisioner_module._build_volume_mounts("thread-1")
        userdata_mount = mounts[1]
        assert userdata_mount.sub_path is None

    def test_pvc_sets_subpath(self, provisioner_module):
        """PVC mode should set sub_path to threads/{thread_id}/user-data."""
        provisioner_module.USERDATA_PVC_NAME = "my-pvc"
        mounts = provisioner_module._build_volume_mounts("thread-42")
        userdata_mount = mounts[1]
        assert userdata_mount.sub_path == "threads/thread-42/user-data"

    def test_skills_mount_read_only(self, provisioner_module):
        """Skills mount should always be read-only."""
        mounts = provisioner_module._build_volume_mounts("thread-1")
        assert mounts[0].read_only is True

    def test_userdata_mount_read_write(self, provisioner_module):
        """User-data mount should always be read-write."""
        mounts = provisioner_module._build_volume_mounts("thread-1")
        assert mounts[1].read_only is False

    def test_mount_paths_are_stable(self, provisioner_module):
        """Mount paths must stay /mnt/skills and /mnt/user-data."""
        mounts = provisioner_module._build_volume_mounts("thread-1")
        assert mounts[0].mount_path == "/mnt/skills"
        assert mounts[1].mount_path == "/mnt/user-data"

    def test_mount_names_match_volumes(self, provisioner_module):
        """Mount names should match the volume names."""
        mounts = provisioner_module._build_volume_mounts("thread-1")
        assert mounts[0].name == "skills"
        assert mounts[1].name == "user-data"

    def test_returns_two_mounts(self, provisioner_module):
        """Should always return exactly two mounts."""
        assert len(provisioner_module._build_volume_mounts("t")) == 2


# ── _build_pod integration ─────────────────────────────────────────────


class TestBuildPodVolumes:
    """Integration: _build_pod should wire volumes and mounts correctly."""

    def test_pod_spec_has_volumes(self, provisioner_module):
        """Pod spec should contain exactly 2 volumes."""
        provisioner_module.SKILLS_PVC_NAME = ""
        provisioner_module.USERDATA_PVC_NAME = ""
        pod = provisioner_module._build_pod("sandbox-1", "thread-1")
        assert len(pod.spec.volumes) == 2

    def test_pod_spec_has_volume_mounts(self, provisioner_module):
        """Container should have exactly 2 volume mounts."""
        provisioner_module.SKILLS_PVC_NAME = ""
        provisioner_module.USERDATA_PVC_NAME = ""
        pod = provisioner_module._build_pod("sandbox-1", "thread-1")
        assert len(pod.spec.containers[0].volume_mounts) == 2

    def test_pod_pvc_mode(self, provisioner_module):
        """Pod should use PVC volumes when PVC names are configured."""
        provisioner_module.SKILLS_PVC_NAME = "skills-pvc"
        provisioner_module.USERDATA_PVC_NAME = "userdata-pvc"
        pod = provisioner_module._build_pod("sandbox-1", "thread-1")
        assert pod.spec.volumes[0].persistent_volume_claim is not None
        assert pod.spec.volumes[1].persistent_volume_claim is not None
        # subPath should be set on user-data mount
        userdata_mount = pod.spec.containers[0].volume_mounts[1]
        assert userdata_mount.sub_path == "threads/thread-1/user-data"
