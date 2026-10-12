"""Small delivery-guard suite; no Docker, network or model calls."""

import importlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
host = importlib.import_module("ecs_native_release_host")
release = importlib.import_module("ecs_native_release")


class DeliveryGuards(unittest.TestCase):
    def lock(self):
        return {
            "format_version": 1,
            "release_id": "deerflow-42",
            "source_commit": "a" * 40,
            "source_archive_sha256": "b" * 64,
            "image": "sha256:" + "c" * 64,
            "image_archive_sha256": "d" * 64,
            "image_archive_bytes": 12,
            "native_revision": host.NATIVE_REVISION,
            "executor_revision": host.EXECUTOR_REVISION,
        }

    def test_only_immutable_matching_generation_is_accepted(self):
        host.validate_lock(self.lock())
        for key, value in [
            ("image", "deerflow:latest"),
            ("native_revision", "unknown"),
            ("release_id", "../other"),
            ("image_archive_bytes", 0),
        ]:
            lock = self.lock()
            lock[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                host.validate_lock(lock)

    def test_failed_or_busy_admission_cannot_be_treated_as_idle(self):
        good = {
            "operator_drain": True,
            "unreleased": 0,
            "native_active": 0,
            "native_revision": host.NATIVE_REVISION,
            "executor_revision": host.EXECUTOR_REVISION,
        }
        host.require_idle(good)
        for key, value in [
            ("operator_drain", False),
            ("unreleased", 1),
            ("native_active", 1),
            ("executor_revision", "future"),
        ]:
            status = {**good, key: value}
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                host.require_idle(status)

    def test_environment_receipt_cannot_cross_release_or_target(self):
        lock = self.lock()
        receipt = release.binding(lock, "e" * 64)
        release.require_binding(receipt, lock, "e" * 64)
        with self.assertRaises(ValueError):
            release.require_binding(receipt, lock, "f" * 64)
        with self.assertRaises(ValueError):
            release.require_binding(
                receipt, {**lock, "image": "sha256:" + "f" * 64}, "e" * 64
            )

    def test_partial_stop_failure_preserves_evidence_without_activation(self):
        calls = []
        lock = self.lock()
        targets = {role: {"role": role} for role in ("controller", "worker")}

        def remote(target, selected, step, baseline):
            calls.append((target["role"], step))
            if step == "stop":
                raise RuntimeError("Physical STOP not confirmed")
            return {"baseline": {"postgres": "retained"}}

        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory).resolve()
            host.exclusive_json(
                directory / "transfer.json", release.binding(lock, "e" * 64)
            )
            with (
                patch.object(
                    release, "loaded", return_value=(directory, lock, targets, "e" * 64)
                ),
                patch.object(release, "remote", side_effect=remote),
            ):
                with self.assertRaises(RuntimeError):
                    release.deploy(SimpleNamespace())
            self.assertEqual(
                calls,
                [
                    ("controller", "preflight"),
                    ("worker", "preflight"),
                    ("controller", "fence"),
                    ("worker", "stop"),
                ],
            )
            self.assertFalse((directory / "deploy.json").exists())
            failure = host.private_json(directory / "deploy-failure.json")
            self.assertEqual(len(failure["completed"]), 3)
            self.assertFalse(failure["admission_resume_attempted"])
            self.assertEqual(len(list(directory.glob("deploy-0*.json"))), 3)

    def test_private_inputs_reject_symlink_and_public_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory).resolve() / "input.json"
            path.write_text(json.dumps(self.lock()))
            path.chmod(0o600)
            self.assertEqual(host.private_json(path), self.lock())
            link = path.parent / "link.json"
            link.symlink_to(path)
            with self.assertRaises(ValueError):
                host.private_json(link)
            path.chmod(0o644)
            with self.assertRaises(ValueError):
                host.private_json(path)


if __name__ == "__main__":
    unittest.main()
