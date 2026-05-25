"""ISSUE-02 regression tests: unified status enums, canonical mapping, failure classification."""

import warnings

import pytest

from deerflow.shared.status import (
    FAILURE_MESSAGES,
    RECOVERABLE_ACTIONS,
    ArtifactStatus,
    FailedLayer,
    RunFailureCategory,
    RunStatus,
    ThreadStatus,
    UploadStatus,
    canonical_run_status,
    get_failure_message,
    get_recoverable_action,
)


# =============================================================================
# ThreadStatus
# =============================================================================

class TestThreadStatus:
    def test_thread_has_three_states(self):
        assert set(ThreadStatus) == {
            ThreadStatus.idle,
            ThreadStatus.active,
            ThreadStatus.archived,
        }

    def test_thread_status_values(self):
        assert ThreadStatus.idle.value == "idle"
        assert ThreadStatus.active.value == "active"
        assert ThreadStatus.archived.value == "archived"


# =============================================================================
# RunStatus
# =============================================================================

class TestRunStatus:
    def test_canonical_values(self):
        """Canonical states match ISSUE-01 baseline."""
        assert RunStatus.pending.value == "pending"
        assert RunStatus.running.value == "running"
        assert RunStatus.success.value == "success"
        assert RunStatus.failed.value == "failed"
        assert RunStatus.cancelled.value == "cancelled"

    def test_deprecated_values_still_accessible(self):
        """Old values still exist for backward compatibility."""
        assert RunStatus.error.value == "error"
        assert RunStatus.timeout.value == "timeout"
        assert RunStatus.interrupted.value == "interrupted"

    def test_canonical_run_status_maps_error_to_failed(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = canonical_run_status("error")
            assert result == RunStatus.failed
            assert len(w) == 1
            assert "deprecated" in str(w[0].message).lower()

    def test_canonical_run_status_maps_timeout_to_failed(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            assert canonical_run_status("timeout") == RunStatus.failed
            assert len(w) == 1

    def test_canonical_run_status_maps_interrupted_to_failed(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            assert canonical_run_status("interrupted") == RunStatus.failed
            assert len(w) == 1

    def test_canonical_run_status_passes_through_canonical(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            assert canonical_run_status("pending") == RunStatus.pending
            assert canonical_run_status("running") == RunStatus.running
            assert canonical_run_status("success") == RunStatus.success
            assert canonical_run_status("failed") == RunStatus.failed
            assert canonical_run_status("cancelled") == RunStatus.cancelled
            assert len(w) == 0

    def test_canonical_run_status_raises_on_invalid(self):
        with pytest.raises(ValueError):
            canonical_run_status("nonexistent")


# =============================================================================
# UploadStatus
# =============================================================================

class TestUploadStatus:
    def test_upload_four_states(self):
        assert set(UploadStatus) == {
            UploadStatus.uploading,
            UploadStatus.converting,
            UploadStatus.ready,
            UploadStatus.failed,
        }

    def test_upload_status_values(self):
        assert UploadStatus.uploading.value == "uploading"
        assert UploadStatus.converting.value == "converting"
        assert UploadStatus.ready.value == "ready"
        assert UploadStatus.failed.value == "failed"


# =============================================================================
# ArtifactStatus
# =============================================================================

class TestArtifactStatus:
    def test_artifact_three_states(self):
        assert set(ArtifactStatus) == {
            ArtifactStatus.generating,
            ArtifactStatus.ready,
            ArtifactStatus.failed,
        }

    def test_artifact_status_values(self):
        assert ArtifactStatus.generating.value == "generating"
        assert ArtifactStatus.ready.value == "ready"
        assert ArtifactStatus.failed.value == "failed"


# =============================================================================
# RunFailureCategory
# =============================================================================

class TestRunFailureCategory:
    def test_three_categories(self):
        assert set(RunFailureCategory) == {
            RunFailureCategory.execution_failed,
            RunFailureCategory.upload_failed,
            RunFailureCategory.external_dependency_unavailable,
        }

    def test_category_values(self):
        assert RunFailureCategory.execution_failed.value == "execution_failed"
        assert RunFailureCategory.upload_failed.value == "upload_failed"
        assert RunFailureCategory.external_dependency_unavailable.value == "external_dependency_unavailable"


# =============================================================================
# FailedLayer
# =============================================================================

class TestFailedLayer:
    def test_three_layers(self):
        assert set(FailedLayer) == {
            FailedLayer.runtime,
            FailedLayer.gateway,
            FailedLayer.external,
        }

    def test_layer_values(self):
        assert FailedLayer.runtime.value == "runtime"
        assert FailedLayer.gateway.value == "gateway"
        assert FailedLayer.external.value == "external"


# =============================================================================
# Failure messages & recoverable actions
# =============================================================================

class TestFailureMessages:
    def test_all_categories_have_messages(self):
        for category in RunFailureCategory:
            assert category.value in FAILURE_MESSAGES
            for lang in ("en", "zh"):
                assert lang in FAILURE_MESSAGES[category.value]

    def test_all_categories_have_actions(self):
        for category in RunFailureCategory:
            assert category.value in RECOVERABLE_ACTIONS
            for lang in ("en", "zh"):
                assert lang in RECOVERABLE_ACTIONS[category.value]

    def test_get_failure_message_defaults_to_en(self):
        msg = get_failure_message("execution_failed", lang="xx")
        assert len(msg) > 0
        assert msg == FAILURE_MESSAGES["execution_failed"]["en"]

    def test_get_recoverable_action_defaults_to_en(self):
        action = get_recoverable_action("upload_failed", lang="xx")
        assert len(action) > 0
        assert action == RECOVERABLE_ACTIONS["upload_failed"]["en"]

    def test_get_failure_message_chinese(self):
        msg = get_failure_message("external_dependency_unavailable", lang="zh")
        assert "外部服务" in msg

    def test_get_recoverable_action_per_category(self):
        assert "Retry" in get_recoverable_action("execution_failed")
        assert "upload" in get_recoverable_action("upload_failed").lower()
        assert "Wait" in get_recoverable_action("external_dependency_unavailable")


# =============================================================================
# ISSUE-02: canonical_run_status mapping & spelling regression
# =============================================================================


class TestCanonicalRunStatusMapping:
    """ISSUE-02: deprecated status values map to failed with DeprecationWarning."""

    def test_error_maps_to_failed(self):
        with pytest.warns(DeprecationWarning, match="deprecated"):
            result = canonical_run_status("error")
        assert result == RunStatus.failed

    def test_timeout_maps_to_failed(self):
        with pytest.warns(DeprecationWarning, match="deprecated"):
            result = canonical_run_status("timeout")
        assert result == RunStatus.failed

    def test_interrupted_maps_to_failed(self):
        with pytest.warns(DeprecationWarning, match="deprecated"):
            result = canonical_run_status("interrupted")
        assert result == RunStatus.failed

    def test_pending_passes_through(self):
        result = canonical_run_status("pending")
        assert result == RunStatus.pending

    def test_running_passes_through(self):
        result = canonical_run_status("running")
        assert result == RunStatus.running

    def test_success_passes_through(self):
        result = canonical_run_status("success")
        assert result == RunStatus.success

    def test_failed_passes_through(self):
        result = canonical_run_status("failed")
        assert result == RunStatus.failed

    def test_cancelled_passes_through(self):
        result = canonical_run_status("cancelled")
        assert result == RunStatus.cancelled


class TestCancelledSpelling:
    """ISSUE-02: canonical spelling is 'cancelled' (double-l), not 'canceled'."""

    def test_run_status_uses_cancelled_not_canceled(self):
        assert RunStatus.cancelled.value == "cancelled"
        assert "cancelled" in {m.value for m in RunStatus}
        assert "canceled" not in {m.value for m in RunStatus}

    def test_canonical_run_status_cancelled(self):
        result = canonical_run_status("cancelled")
        assert result == RunStatus.cancelled
