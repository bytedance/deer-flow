"""Regression tests for provisioner three-way skills + PVC volume support."""


# ── _build_volumes ─────────────────────────────────────────────────────


class TestBuildVolumes:
    """Tests for _build_volumes: hostPath three-way vs PVC fallback."""

    # ── hostPath mode (default) ────────────────────────────────────────

    def test_hostpath_without_legacy_returns_three_volumes(self, provisioner_module):
        """hostPath mode omits legacy volume unless the backend requests it."""
        provisioner_module.SKILLS_PVC_NAME = ""
        provisioner_module.USERDATA_PVC_NAME = ""
        volumes = provisioner_module._build_volumes("thread-1")
        assert len(volumes) == 3

    def test_hostpath_skills_public_volume(self, provisioner_module):
        """First skills volume mounts public/ subdirectory."""
        provisioner_module.SKILLS_PVC_NAME = ""
        volumes = provisioner_module._build_volumes("thread-1")
        pub = volumes[0]
        assert pub.name == "skills-public"
        assert pub.host_path is not None
        assert pub.host_path.path.endswith("/public")
        assert pub.host_path.type == "Directory"
        assert pub.persistent_volume_claim is None

    def test_hostpath_skills_custom_volume(self, provisioner_module):
        """Second skills volume mounts per-user custom directory."""
        provisioner_module.SKILLS_PVC_NAME = ""
        volumes = provisioner_module._build_volumes("thread-1", user_id="user-7")
        custom = volumes[1]
        assert custom.name == "skills-custom"
        assert custom.host_path is not None
        assert "users/user-7/skills/custom" in custom.host_path.path
        assert custom.host_path.type == "DirectoryOrCreate"

    def test_hostpath_skills_legacy_volume(self, provisioner_module):
        """Legacy global-custom directory is mounted only when requested."""
        provisioner_module.SKILLS_PVC_NAME = ""
        volumes = provisioner_module._build_volumes(
            "thread-1",
            include_legacy_skills=True,
        )
        legacy = volumes[2]
        assert legacy.name == "skills-legacy"
        assert legacy.host_path is not None
        assert legacy.host_path.path.endswith("/custom")
        assert legacy.host_path.type == "Directory"

    def test_hostpath_without_legacy_has_no_legacy_volume(self, provisioner_module):
        """Fresh installs should not require a missing global legacy directory."""
        provisioner_module.SKILLS_PVC_NAME = ""
        volumes = provisioner_module._build_volumes("thread-1")
        assert [volume.name for volume in volumes] == [
            "skills-public",
            "skills-custom",
            "user-data",
        ]

    def test_hostpath_userdata_includes_thread_id(self, provisioner_module):
        """hostPath user-data path should include thread_id."""
        provisioner_module.USERDATA_PVC_NAME = ""
        volumes = provisioner_module._build_volumes("my-thread-42")
        userdata_vol = volumes[-1]
        path = userdata_vol.host_path.path
        assert "my-thread-42" in path
        assert path.endswith("user-data")
        assert userdata_vol.host_path.type == "DirectoryOrCreate"

    # ── PVC mode (single-volume fallback) ──────────────────────────────

    def test_pvc_returns_two_volumes(self, provisioner_module):
        """PVC mode falls back to 1 skills volume + 1 user-data volume."""
        provisioner_module.SKILLS_PVC_NAME = "my-skills-pvc"
        provisioner_module.USERDATA_PVC_NAME = ""
        volumes = provisioner_module._build_volumes("thread-1")
        assert len(volumes) == 2

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
        userdata_vol = volumes[-1]
        assert userdata_vol.persistent_volume_claim is not None
        assert userdata_vol.persistent_volume_claim.claim_name == "my-userdata-pvc"
        assert userdata_vol.host_path is None

    def test_both_pvc_set(self, provisioner_module):
        """When both PVC names are set, both volumes use PVC."""
        provisioner_module.SKILLS_PVC_NAME = "skills-pvc"
        provisioner_module.USERDATA_PVC_NAME = "userdata-pvc"
        volumes = provisioner_module._build_volumes("thread-1")
        assert volumes[0].persistent_volume_claim is not None
        assert volumes[-1].persistent_volume_claim is not None

    def test_pvc_volume_names_are_stable(self, provisioner_module):
        """PVC mode volume names must stay 'skills' and 'user-data'."""
        provisioner_module.SKILLS_PVC_NAME = "x"
        volumes = provisioner_module._build_volumes("thread-1")
        assert volumes[0].name == "skills"
        assert volumes[-1].name == "user-data"


# ── _build_volume_mounts ───────────────────────────────────────────────


class TestBuildVolumeMounts:
    """Tests for _build_volume_mounts: three-way mount paths and subPath."""

    # ── hostPath mode ──────────────────────────────────────────────────

    def test_hostpath_without_legacy_returns_three_mounts(self, provisioner_module):
        """hostPath mode omits legacy mount unless the backend requests it."""
        provisioner_module.SKILLS_PVC_NAME = ""
        provisioner_module.USERDATA_PVC_NAME = ""
        mounts = provisioner_module._build_volume_mounts("thread-1")
        assert len(mounts) == 3

    def test_hostpath_skills_public_mount(self, provisioner_module):
        """Public skills mount at /mnt/skills/public, read-only."""
        provisioner_module.SKILLS_PVC_NAME = ""
        mounts = provisioner_module._build_volume_mounts("thread-1")
        assert mounts[0].name == "skills-public"
        assert mounts[0].mount_path == "/mnt/skills/public"
        assert mounts[0].read_only is True

    def test_hostpath_skills_custom_mount(self, provisioner_module):
        """Per-user custom skills mount at /mnt/skills/custom, read-only."""
        provisioner_module.SKILLS_PVC_NAME = ""
        mounts = provisioner_module._build_volume_mounts("thread-1")
        assert mounts[1].name == "skills-custom"
        assert mounts[1].mount_path == "/mnt/skills/custom"
        assert mounts[1].read_only is True

    def test_hostpath_skills_legacy_mount(self, provisioner_module):
        """Legacy skills mount at /mnt/skills/legacy, read-only."""
        provisioner_module.SKILLS_PVC_NAME = ""
        mounts = provisioner_module._build_volume_mounts(
            "thread-1",
            include_legacy_skills=True,
        )
        assert mounts[2].name == "skills-legacy"
        assert mounts[2].mount_path == "/mnt/skills/legacy"
        assert mounts[2].read_only is True

    def test_hostpath_without_legacy_has_no_legacy_mount(self, provisioner_module):
        """Users with custom skills should not see hidden legacy content in the sandbox."""
        provisioner_module.SKILLS_PVC_NAME = ""
        mounts = provisioner_module._build_volume_mounts("thread-1")
        assert [mount.name for mount in mounts] == [
            "skills-public",
            "skills-custom",
            "user-data",
        ]

    def test_hostpath_userdata_read_write(self, provisioner_module):
        """User-data mount should always be read-write."""
        provisioner_module.SKILLS_PVC_NAME = ""
        mounts = provisioner_module._build_volume_mounts("thread-1")
        userdata = mounts[-1]
        assert userdata.name == "user-data"
        assert userdata.mount_path == "/mnt/user-data"
        assert userdata.read_only is False

    # ── PVC mode ───────────────────────────────────────────────────────

    def test_pvc_returns_two_mounts(self, provisioner_module):
        """PVC mode falls back to 1 skills mount + 1 user-data mount."""
        provisioner_module.SKILLS_PVC_NAME = "x"
        mounts = provisioner_module._build_volume_mounts("thread-1")
        assert len(mounts) == 2

    def test_pvc_skills_mount_is_single_root(self, provisioner_module):
        """PVC mode skills mount is at /mnt/skills."""
        provisioner_module.SKILLS_PVC_NAME = "x"
        mounts = provisioner_module._build_volume_mounts("thread-1")
        assert mounts[0].mount_path == "/mnt/skills"

    def test_pvc_no_subpath_on_userdata(self, provisioner_module):
        """hostPath mode should not set sub_path on user-data mount."""
        provisioner_module.USERDATA_PVC_NAME = ""
        mounts = provisioner_module._build_volume_mounts("thread-1")
        userdata_mount = mounts[-1]
        assert userdata_mount.sub_path is None

    def test_skills_pvc_does_not_set_subpath_by_default(self, provisioner_module):
        """PVC-backed skills keep legacy root mount unless explicitly configured."""
        provisioner_module.SKILLS_PVC_NAME = "my-skills-pvc"
        provisioner_module.SKILLS_PVC_SUBPATH_TEMPLATE = ""
        mounts = provisioner_module._build_volume_mounts("thread-42", user_id="user-7")
        skills_mount = mounts[0]
        assert skills_mount.sub_path is None

    def test_skills_pvc_can_use_user_scoped_subpath_template(self, provisioner_module):
        """Operators can opt into per-user/thread skills subPath for shared PVCs."""
        provisioner_module.SKILLS_PVC_NAME = "my-skills-pvc"
        provisioner_module.SKILLS_PVC_SUBPATH_TEMPLATE = "deer-flow/users/{user_id}/threads/{thread_id}/skills"
        mounts = provisioner_module._build_volume_mounts("thread-42", user_id="user-7")
        skills_mount = mounts[0]
        assert skills_mount.sub_path == "deer-flow/users/user-7/threads/thread-42/skills"

    def test_pvc_sets_user_scoped_subpath(self, provisioner_module):
        """PVC mode should include user_id in the user-data subPath."""
        provisioner_module.USERDATA_PVC_NAME = "my-pvc"
        mounts = provisioner_module._build_volume_mounts("thread-42", user_id="user-7")
        userdata_mount = mounts[-1]
        assert userdata_mount.sub_path == "deer-flow/users/user-7/threads/thread-42/user-data"

    def test_pvc_defaults_to_default_user_subpath(self, provisioner_module):
        """Older callers should still land under a stable default user namespace."""
        provisioner_module.USERDATA_PVC_NAME = "my-pvc"
        mounts = provisioner_module._build_volume_mounts("thread-42")
        userdata_mount = mounts[-1]
        assert userdata_mount.sub_path == "deer-flow/users/default/threads/thread-42/user-data"


# ── _build_pod integration ─────────────────────────────────────────────


class TestBuildPodVolumes:
    """Integration: _build_pod should wire volumes and mounts correctly."""

    def test_pod_hostpath_without_legacy_has_three_volumes(self, provisioner_module):
        """hostPath Pod spec should omit legacy volume by default."""
        provisioner_module.SKILLS_PVC_NAME = ""
        provisioner_module.USERDATA_PVC_NAME = ""
        pod = provisioner_module._build_pod("sandbox-1", "thread-1")
        assert len(pod.spec.volumes) == 3

    def test_pod_hostpath_without_legacy_has_three_mounts(self, provisioner_module):
        """hostPath container should omit legacy mount by default."""
        provisioner_module.SKILLS_PVC_NAME = ""
        provisioner_module.USERDATA_PVC_NAME = ""
        pod = provisioner_module._build_pod("sandbox-1", "thread-1")
        assert len(pod.spec.containers[0].volume_mounts) == 3

    def test_pod_hostpath_with_legacy_has_four_volumes(self, provisioner_module):
        """Legacy volume should be present when the backend requests it."""
        provisioner_module.SKILLS_PVC_NAME = ""
        provisioner_module.USERDATA_PVC_NAME = ""
        pod = provisioner_module._build_pod(
            "sandbox-1",
            "thread-1",
            include_legacy_skills=True,
        )
        assert len(pod.spec.volumes) == 4

    def test_pod_hostpath_with_legacy_has_four_mounts(self, provisioner_module):
        """Legacy mount should be present when the backend requests it."""
        provisioner_module.SKILLS_PVC_NAME = ""
        provisioner_module.USERDATA_PVC_NAME = ""
        pod = provisioner_module._build_pod(
            "sandbox-1",
            "thread-1",
            include_legacy_skills=True,
        )
        assert len(pod.spec.containers[0].volume_mounts) == 4

    def test_pod_pvc_has_two_volumes(self, provisioner_module):
        """PVC Pod spec should contain exactly 2 volumes."""
        provisioner_module.SKILLS_PVC_NAME = "skills-pvc"
        provisioner_module.USERDATA_PVC_NAME = ""
        pod = provisioner_module._build_pod("sandbox-1", "thread-1")
        assert len(pod.spec.volumes) == 2

    def test_pod_pvc_has_two_mounts(self, provisioner_module):
        """PVC container should have exactly 2 volume mounts."""
        provisioner_module.SKILLS_PVC_NAME = "skills-pvc"
        provisioner_module.USERDATA_PVC_NAME = ""
        pod = provisioner_module._build_pod("sandbox-1", "thread-1")
        assert len(pod.spec.containers[0].volume_mounts) == 2

    def test_pod_pvc_mode_uses_user_scoped_subpath(self, provisioner_module):
        """Pod should use a user-scoped subPath for PVC user-data."""
        provisioner_module.SKILLS_PVC_NAME = "skills-pvc"
        provisioner_module.USERDATA_PVC_NAME = "userdata-pvc"
        pod = provisioner_module._build_pod("sandbox-1", "thread-1", user_id="user-7")
        assert pod.spec.volumes[0].persistent_volume_claim is not None
        assert pod.spec.volumes[-1].persistent_volume_claim is not None
        userdata_mount = pod.spec.containers[0].volume_mounts[-1]
        assert userdata_mount.sub_path == "deer-flow/users/user-7/threads/thread-1/user-data"

    def test_pod_three_way_skills_mount_paths(self, provisioner_module):
        """Ensure public/custom/legacy mount paths are correct."""
        provisioner_module.SKILLS_PVC_NAME = ""
        provisioner_module.USERDATA_PVC_NAME = ""
        pod = provisioner_module._build_pod(
            "sandbox-1",
            "thread-1",
            include_legacy_skills=True,
        )
        mount_paths = {m.name: m.mount_path for m in pod.spec.containers[0].volume_mounts}
        assert mount_paths["skills-public"] == "/mnt/skills/public"
        assert mount_paths["skills-custom"] == "/mnt/skills/custom"
        assert mount_paths["skills-legacy"] == "/mnt/skills/legacy"

    def test_pod_pvc_mode_can_use_user_scoped_skills_subpath(self, provisioner_module):
        """Pod should use a configured user-scoped subPath for PVC skills."""
        provisioner_module.SKILLS_PVC_NAME = "skills-pvc"
        provisioner_module.SKILLS_PVC_SUBPATH_TEMPLATE = "deer-flow/users/{user_id}/threads/{thread_id}/skills"
        provisioner_module.USERDATA_PVC_NAME = "userdata-pvc"
        pod = provisioner_module._build_pod("sandbox-1", "thread-1", user_id="user-7")
        skills_mount = pod.spec.containers[0].volume_mounts[0]
        assert skills_mount.sub_path == "deer-flow/users/user-7/threads/thread-1/skills"
