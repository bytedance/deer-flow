"""Unit tests for AgentIdentity and identity-related path resolution."""

import pytest

from deerflow.identity.agent_identity import AgentIdentity, _validate_id


# ── _validate_id ────────────────────────────────────────────────────────────────

class TestValidateId:
    def test_valid_alphanumeric(self):
        assert _validate_id("research", "dept_id") == "research"

    def test_valid_with_dash(self):
        assert _validate_id("sci-agent", "agent_name") == "sci-agent"

    def test_valid_with_dot_and_underscore(self):
        assert _validate_id("alice_v2.1", "user_id") == "alice_v2.1"

    def test_none_passthrough(self):
        assert _validate_id(None, "dept_id") is None

    def test_invalid_slash(self):
        with pytest.raises(ValueError, match="Invalid dept_id"):
            _validate_id("a/b", "dept_id")

    def test_invalid_space(self):
        with pytest.raises(ValueError, match="Invalid user_id"):
            _validate_id("alice bob", "user_id")

    def test_too_long(self):
        with pytest.raises(ValueError):
            _validate_id("a" * 65, "agent_name")

    def test_empty_string_invalid(self):
        with pytest.raises(ValueError):
            _validate_id("", "dept_id")


# ── AgentIdentity construction ──────────────────────────────────────────────────

class TestAgentIdentityConstruction:
    def test_full_identity(self):
        identity = AgentIdentity(dept_id="research", user_id="alice", agent_name="sci-agent")
        assert identity.dept_id == "research"
        assert identity.user_id == "alice"
        assert identity.agent_name == "sci-agent"

    def test_global_identity(self):
        identity = AgentIdentity()
        assert identity.dept_id is None
        assert identity.user_id is None
        assert identity.agent_name is None
        assert identity.is_global is True

    def test_dept_only(self):
        identity = AgentIdentity(dept_id="research")
        assert identity.is_global is False
        assert identity.has_dept is True
        assert identity.has_user is False

    def test_invalid_dept_id_raises(self):
        with pytest.raises(ValueError):
            AgentIdentity(dept_id="bad/id")

    def test_from_config_full(self):
        config = {"configurable": {"dept_id": "research", "user_id": "alice", "agent_name": "sci-agent"}}
        identity = AgentIdentity.from_config(config)
        assert identity.dept_id == "research"
        assert identity.user_id == "alice"
        assert identity.agent_name == "sci-agent"

    def test_from_config_empty(self):
        identity = AgentIdentity.from_config({})
        assert identity.is_global is True

    def test_from_config_none(self):
        identity = AgentIdentity.from_config(None)
        assert identity.is_global is True

    def test_from_config_empty_string_treated_as_none(self):
        config = {"configurable": {"dept_id": "", "user_id": "alice"}}
        identity = AgentIdentity.from_config(config)
        # empty string → None (is_global depends on user_id)
        assert identity.dept_id is None
        assert identity.user_id == "alice"


# ── OV header properties ────────────────────────────────────────────────────────

class TestOVHeaders:
    def test_full_identity_headers(self):
        identity = AgentIdentity(dept_id="research", user_id="alice", agent_name="sci-agent")
        headers = identity.ov_headers
        assert headers["X-OpenViking-Account"] == "research"
        assert headers["X-OpenViking-User"] == "alice"
        assert headers["X-OpenViking-Agent"] == "sci-agent"

    def test_global_identity_uses_default(self):
        identity = AgentIdentity()
        assert identity.ov_account == "default"
        assert identity.ov_user == "default"
        assert identity.ov_agent == "default"

    def test_partial_identity_uses_default_for_missing(self):
        identity = AgentIdentity(dept_id="research")
        assert identity.ov_account == "research"
        assert identity.ov_user == "default"
        assert identity.ov_agent == "default"


# ── Predicates ──────────────────────────────────────────────────────────────────

class TestPredicates:
    def test_is_global_no_dept_no_user(self):
        assert AgentIdentity().is_global is True
        assert AgentIdentity(agent_name="sci-agent").is_global is True  # agent alone is not enough

    def test_is_global_false_with_dept(self):
        assert AgentIdentity(dept_id="research").is_global is False

    def test_has_dept_has_user_has_agent(self):
        i = AgentIdentity(dept_id="d", user_id="u", agent_name="a")
        assert i.has_dept is True
        assert i.has_user is True
        assert i.has_agent is True

    def test_predicates_false_when_absent(self):
        i = AgentIdentity()
        assert i.has_dept is False
        assert i.has_user is False
        assert i.has_agent is False

    def test_str_representation_full(self):
        i = AgentIdentity(dept_id="research", user_id="alice", agent_name="sci-agent")
        assert "dept=research" in str(i)
        assert "user=alice" in str(i)
        assert "agent=sci-agent" in str(i)

    def test_str_representation_global(self):
        assert str(AgentIdentity()) == "AgentIdentity(global)"


# ── Path isolation via Paths ─────────────────────────────────────────────────────

class TestIdentityPaths:
    def test_memory_paths_are_distinct(self, tmp_path):
        from deerflow.config.paths import Paths

        paths = Paths(tmp_path)

        alice = AgentIdentity(dept_id="research", user_id="alice", agent_name="sci-agent")
        bob = AgentIdentity(dept_id="research", user_id="bob", agent_name="sci-agent")

        alice_mem = paths.identity_memory_file(alice)
        bob_mem = paths.identity_memory_file(bob)
        assert alice_mem != bob_mem
        assert "alice" in str(alice_mem)
        assert "bob" in str(bob_mem)

    def test_global_memory_file(self, tmp_path):
        from deerflow.config.paths import Paths

        paths = Paths(tmp_path)
        global_identity = AgentIdentity()
        assert paths.identity_memory_file(global_identity) == paths.memory_file

    def test_workspace_dirs_are_distinct(self, tmp_path):
        from deerflow.config.paths import Paths

        paths = Paths(tmp_path)
        alice = AgentIdentity(dept_id="d", user_id="alice", agent_name="agent1")
        bob = AgentIdentity(dept_id="d", user_id="bob", agent_name="agent1")
        assert paths.identity_workspace_dir(alice) != paths.identity_workspace_dir(bob)

    def test_workspace_dir_none_without_agent(self, tmp_path):
        from deerflow.config.paths import Paths

        paths = Paths(tmp_path)
        identity = AgentIdentity(dept_id="d", user_id="u")  # no agent
        assert paths.identity_workspace_dir(identity) is None

    def test_config_files_ordering(self, tmp_path):
        from deerflow.config.paths import Paths

        paths = Paths(tmp_path)
        identity = AgentIdentity(dept_id="research", user_id="alice", agent_name="sci-agent")
        cfg_files = paths.identity_config_files(identity)
        # Must be in order: global, dept, user, agent
        paths_str = [str(p) for p in cfg_files]
        assert len(paths_str) == 4
        # Global comes first, agent comes last
        assert "depts" not in paths_str[0]
        assert "sci-agent" in paths_str[-1]
