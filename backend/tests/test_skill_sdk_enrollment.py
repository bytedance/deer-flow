"""Standalone SDK processes must not bypass another host's durable enrollment."""

import json
import os
import subprocess
import sys

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from deerflow.config.paths import Paths
from deerflow.persistence.base import Base
from deerflow.persistence.user.model import UserRow
from deerflow.skills.mutations.assets import capture_package
from deerflow.skills.mutations.repository import SkillMutationRepository

CONTENT = "---\nname: example\ndescription: SDK enrollment regression\n---\nOriginal body.\n"


@pytest.fixture
def sdk_home(tmp_path):
    home = tmp_path / "home"
    root = Paths(base_dir=home).user_custom_skills_dir("owner") / "example"
    root.mkdir(parents=True)
    (root / "SKILL.md").write_text(CONTENT, encoding="utf-8")
    public = tmp_path / "skills" / "public" / "example"
    public.mkdir(parents=True)
    (public / "SKILL.md").write_text(CONTENT, encoding="utf-8")
    config = tmp_path / "config.yaml"
    config.write_text(
        json.dumps(
            {
                "models": [{"name": "test", "use": "langchain_openai:ChatOpenAI", "model": "test", "api_key": "test"}],
                "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
                "skills": {"path": str(tmp_path / "skills")},
                "database": {"backend": "sqlite", "sqlite_dir": str(tmp_path)},
                "plugins": [],
            }
        ),
        encoding="utf-8",
    )
    extensions = tmp_path / "extensions.json"
    extensions.write_text('{"skills": {}}', encoding="utf-8")
    engine = create_engine(f"sqlite:///{tmp_path / 'deerflow.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    with sessions.begin() as session:
        session.add(UserRow(id="owner", email="owner@example.test"))
    repository = SkillMutationRepository(sessions)
    yield tmp_path, config, root, repository
    engine.dispose()


def run_sdk(fixture, action, *, owner="owner"):
    tmp_path, config, _, _ = fixture
    source = """
import json, sys
from types import SimpleNamespace
from deerflow.client import DeerFlowClient
from deerflow.runtime.user_context import set_current_user
from deerflow.skills.mutations import guard
from deerflow.skills.storage import get_or_new_user_skill_storage
from deerflow_extension_api import HostCapabilityError
assert guard._runtime is None
set_current_user(SimpleNamespace(id=sys.argv[2]))
client = DeerFlowClient(config_path=sys.argv[1])
storage = get_or_new_user_skill_storage(sys.argv[2], app_config=client._app_config)
try:
    exec(sys.argv[3])
except HostCapabilityError as exc:
    print(json.dumps({"error": exc.code}))
else:
    print(json.dumps({"error": None}))
"""
    result = subprocess.run(
        [sys.executable, "-c", source, str(config), owner, action],
        env={**os.environ, "DEER_FLOW_CONFIG_PATH": str(config), "DEER_FLOW_HOME": str(tmp_path / "home"), "DEER_FLOW_EXTENSIONS_CONFIG_PATH": str(tmp_path / "extensions.json")},
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout.splitlines()[-1])


@pytest.mark.parametrize(
    "action",
    [
        "client.update_skill('example', enabled=False); client.update_skill('example', enabled=True)",
        "storage.set_skill_enabled_state('example', False)",
        "storage.write_custom_skill('example', 'SKILL.md', 'changed')",
        "storage.delete_custom_skill('example')",
        "client.get_skill('example')",
    ],
)
def test_fresh_sdk_refuses_enrolled_owner_without_gateway_runtime(sdk_home, action):
    _, _, root, repository = sdk_home
    before = repository.observe("owner", "example", capture_package(root).digest, True, exists=True)
    assert run_sdk(sdk_home, action) == {"error": "MUTATION_RUNTIME_REQUIRED"}
    assert (root / "SKILL.md").read_text(encoding="utf-8") == CONTENT
    assert not (root.parent.parent / "_skill_states.json").exists()
    after = repository.observe("owner", "example", capture_package(root).digest, True, exists=True)
    assert after.mutation_seq == before.mutation_seq


def test_fresh_sdk_global_toggle_cannot_bypass_another_enrolled_owner(sdk_home):
    _, _, root, repository = sdk_home
    repository.observe("owner", "example", capture_package(root).digest, True, exists=True)
    assert run_sdk(sdk_home, "client.update_skill('example', enabled=False)", owner="other") == {"error": "MUTATION_RUNTIME_REQUIRED"}
    assert json.loads((sdk_home[0] / "extensions.json").read_text(encoding="utf-8")) == {"skills": {}}


def test_unenrolled_sdk_retains_skill_management(sdk_home):
    assert run_sdk(sdk_home, "client.update_skill('example', enabled=False); client.update_skill('example', enabled=True)") == {"error": None}


def test_existing_sdk_rechecks_enrollment_after_an_earlier_unmanaged_read(sdk_home):
    action = """
assert client.get_skill("example") is not None
# Another host can persist enrollment after this client has started. Only the
# durable row is shared; the SDK still has no injected mutation runtime.
import sqlite3
with sqlite3.connect(client._app_config.database.sqlite_path) as connection:
    connection.execute("INSERT INTO skill_mutation_owners (owner_id, generation, deleting) VALUES ('owner', 0, 0)")
storage.set_skill_enabled_state("example", False)
"""
    assert run_sdk(sdk_home, action) == {"error": "MUTATION_RUNTIME_REQUIRED"}
    assert not (sdk_home[2].parent.parent / "_skill_states.json").exists()


def test_sdk_cannot_treat_unavailable_enrollment_as_unmanaged(sdk_home):
    action = """
from pathlib import Path
Path(client._app_config.database.sqlite_path).write_bytes(b"unreadable database")
storage.set_skill_enabled_state("example", False)
"""
    assert run_sdk(sdk_home, action) == {"error": "UNAVAILABLE"}
    assert not (sdk_home[2].parent.parent / "_skill_states.json").exists()


def test_sdk_does_not_create_a_missing_application_database(sdk_home):
    action = """
from pathlib import Path
path = Path(client._app_config.database.sqlite_path)
path.unlink()
client.update_skill("example", enabled=False)
assert not path.exists()
"""
    assert run_sdk(sdk_home, action) == {"error": None}
