"""Packaging checks catch defects before a trusted extension is installed."""

import importlib.util
import json
from pathlib import Path
from zipfile import ZipFile

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_extension.py"
spec = importlib.util.spec_from_file_location("extension_check_script", SCRIPT)
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


def wheel(
    tmp_path,
    *,
    entry="example = example:install",
    requirement="deerflow-extension-api>=0.2,<0.3",
    files=None,
):
    path = tmp_path / "example-0.1.0-py3-none-any.whl"
    with ZipFile(path, "w") as archive:
        archive.writestr(
            "example-0.1.0.dist-info/METADATA",
            f"Metadata-Version: 2.3\nName: example\nVersion: 0.1.0\nRequires-Dist: {requirement}\n",
        )
        archive.writestr(
            "example-0.1.0.dist-info/entry_points.txt",
            f"[deerflow.extensions]\n{entry}\n",
        )
        archive.writestr(
            "example/__init__.py",
            "raise RuntimeError('The checker must not import plugin code')\n",
        )
        for name, content in (files or {}).items():
            archive.writestr(name, content)
    return path


def test_packaged_entry_is_checked_without_importing_plugin(tmp_path):
    checker.check_wheel(tmp_path, wheel(tmp_path))


def test_backend_only_wheel_skips_extraction(tmp_path, monkeypatch):
    def fail_if_extracted(*args, **kwargs):
        pytest.fail("Backend-only wheels must not be extracted")

    monkeypatch.setattr(ZipFile, "extractall", fail_if_extracted)
    checker.check_wheel(tmp_path, wheel(tmp_path))


@pytest.mark.parametrize(
    ("entry", "message"),
    [
        ("example = missing:install", "entry module"),
        ("example = example", "entry point target"),
        ("example = example:factory.install", "entry point target"),
        ("example = example:install\nsecond = example:install", "exactly one"),
    ],
)
def test_invalid_packaged_entry_is_rejected(tmp_path, entry, message):
    with pytest.raises(ValueError, match=message):
        checker.check_wheel(tmp_path, wheel(tmp_path, entry=entry))


def test_dotted_entry_module_is_accepted_without_importing_plugin(tmp_path):
    checker.check_wheel(
        tmp_path,
        wheel(tmp_path, entry="example = example.nested:install", files={"example/nested.py": "raise RuntimeError('The checker must not import plugin code')\n"}),
    )


@pytest.mark.parametrize(
    "requirement",
    [
        "unrelated>=1",
        "deerflow-extension-api>=99",
        'deerflow-extension-api>=0.2; extra == "optional"',
    ],
)
def test_missing_or_incompatible_api_dependency_is_rejected(tmp_path, requirement):
    with pytest.raises(ValueError, match="extension-api"):
        checker.check_wheel(tmp_path, wheel(tmp_path, requirement=requirement))


def test_dropped_manifest_is_detected_from_src_layout(tmp_path):
    package = tmp_path / "src" / "example"
    package.mkdir(parents=True)
    (package / "ui_manifest.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="manifest.*not packaged"):
        checker.check_wheel(tmp_path, wheel(tmp_path))


def test_packaged_assets_use_host_manifest_validation(tmp_path):
    manifest = json.dumps({"schema_version": 1, "entry": "main.mjs", "files": ["main.mjs", "styles.css"]})
    files = {
        "example/ui_manifest.json": manifest,
        "example/main.mjs": "export default {};",
        "example/styles.css": "body {}",
    }
    checker.check_wheel(tmp_path, wheel(tmp_path, files=files))
    del files["example/styles.css"]
    with pytest.raises(FileNotFoundError):
        checker.check_wheel(tmp_path, wheel(tmp_path, files=files))


def test_custom_manifest_can_be_checked_explicitly(tmp_path):
    path = "example/resources.json"
    manifest = json.dumps({"schema_version": 1, "entry": "main.mjs", "files": ["main.mjs"]})
    checker.check_wheel(
        tmp_path,
        wheel(tmp_path, files={path: manifest, "example/main.mjs": "export default {};"}),
        manifests=[path],
    )


def test_wheel_root_manifest_is_also_validated(tmp_path):
    with pytest.raises(ValueError, match="Unsupported browser asset manifest"):
        checker.check_wheel(tmp_path, wheel(tmp_path, files={"ui_manifest.json": "{}"}))


def test_single_module_source_cannot_drop_its_manifest(tmp_path):
    (tmp_path / "example.py").write_text("", encoding="utf-8")
    (tmp_path / "ui_manifest.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="manifest.*not packaged"):
        checker.check_wheel(tmp_path, wheel(tmp_path))


@pytest.mark.parametrize("name", ["../escaped", "/escaped", r"example\escaped", "C:/ui_manifest.json", "C:ui_manifest.json", "C:/example/ui_manifest.json", "C:example/ui_manifest.json"])
def test_wheel_paths_cannot_escape_temporary_directory(tmp_path, monkeypatch, name):
    def fail_if_extracted(*args, **kwargs):
        pytest.fail("Unsafe wheel paths reached extraction")

    # zipfile normalizes os.sep in entry names on Windows, so a wheel built
    # through writestr never carries a verbatim backslash name there. Inject
    # the hostile name into namelist unless the archive already stores it, so
    # the guard contract is exercised with identical bytes on every host.
    real_namelist = ZipFile.namelist

    def namelist_with_hostile_entry(self):
        stored = real_namelist(self)
        return stored if name in stored else [*stored, name]

    monkeypatch.setattr(ZipFile, "extractall", fail_if_extracted)
    monkeypatch.setattr(ZipFile, "namelist", namelist_with_hostile_entry)
    with pytest.raises(ValueError, match="wheel path"):
        checker.check_wheel(tmp_path, wheel(tmp_path, files={name: "no"}))


def test_invalid_packaged_python_is_rejected(tmp_path):
    with pytest.raises(SyntaxError):
        checker.check_wheel(tmp_path, wheel(tmp_path, files={"example/broken.py": "def broken(:\n"}))
