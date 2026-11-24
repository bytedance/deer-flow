"""Offline registration and packaged browser-asset checks."""

import json
import sys
import unittest
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend/packages/extension-api"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

install = import_module("deerflow_extension_office_preview").install


class RegistrationTests(unittest.TestCase):
    def test_registration_has_only_the_browser_contribution(self):
        contributions = []
        install(
            SimpleNamespace(plugin=lambda value: contributions.append(value) or True),
            {},
        )
        contribution = contributions[0]
        self.assertEqual(contribution.namespace, "office-preview")
        self.assertTrue(contribution.enabled)
        self.assertFalse(contribution.backend)
        self.assertFalse(contribution.tools)
        manifest = json.loads(
            (contribution.frontend.root / "ui_manifest.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertIn(manifest["entry"], manifest["files"])
        self.assertEqual(len(set(manifest["files"])), len(manifest["files"]))
        for filename in manifest["files"]:
            asset = contribution.frontend.root / filename
            self.assertTrue(asset.is_file())
            self.assertLess(asset.stat().st_size, 4 * 1024 * 1024)

    def test_disabled_and_invalid_configuration(self):
        contributions = []
        registry = SimpleNamespace(
            plugin=lambda value: contributions.append(value) or True
        )
        install(registry, {"enabled": False})
        self.assertFalse(contributions[0].enabled)
        for enabled in ("false", 1, None):
            with self.assertRaises(ValueError):
                install(registry, {"enabled": enabled})

    def test_unsupported_host_fails_clearly(self):
        with self.assertRaises(RuntimeError):
            install(SimpleNamespace(plugin=lambda value: False), {})


if __name__ == "__main__":
    unittest.main()
