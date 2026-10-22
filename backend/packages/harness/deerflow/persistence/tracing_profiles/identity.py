"""Stable Agent incarnations and the shared deletion critical section."""

from contextlib import contextmanager
from uuid import UUID, uuid4

from sqlalchemy import select

from deerflow.config.extensions_config import extensions_config_file_lock
from deerflow.config.secret_file import read_or_create_secret_file


def file_agent_identity_lock(agent_dir):
    # Keep the lock outside the directory that deletion removes.
    return extensions_config_file_lock(agent_dir.parent / f"{agent_dir.name}.tracing-identity")


def resolve_agent_incarnation(name: str, owner_user_id: str, *, app_config=None) -> str:
    if name == "lead_agent":
        return "builtin:lead_agent"
    from deerflow.persistence.agents import get_agent_store, make_agent_store
    from deerflow.persistence.agents.model import AgentRow
    from deerflow.persistence.agents.sql import SqlAgentStore

    store = make_agent_store(app_config) if app_config is not None else get_agent_store()
    if isinstance(store, SqlAgentStore):
        with store._Session() as session:
            identity = session.scalar(select(AgentRow.id).where(AgentRow.user_id == owner_user_id, AgentRow.name == name))
        if identity is None:
            raise FileNotFoundError("Agent no longer exists")
        return f"db:{identity}"
    return resolve_file_agent_incarnation(name, owner_user_id)


def resolve_file_agent_incarnation(name: str, owner_user_id: str) -> str:
    from deerflow.config.agents_config import resolve_agent_dir

    agent_dir = resolve_agent_dir(name, user_id=owner_user_id)
    with file_agent_identity_lock(agent_dir):
        if not (agent_dir / "config.yaml").is_file():
            raise FileNotFoundError("Agent no longer exists")
        identity = read_or_create_secret_file(agent_dir / ".tracing-incarnation", lambda: uuid4().hex, validate=UUID)
        return f"file:{identity}"


@contextmanager
def file_agent_deletion_transaction():
    """Hold DB fence before the identity file lock, for every file-store caller."""
    from deerflow.config.app_config import AppConfig, get_app_config

    try:
        config = get_app_config()
    except FileNotFoundError:
        # Standalone file-store consumers can run without application config.
        # A configured but broken file must remain an error.
        import os

        if os.environ.get("DEER_FLOW_CONFIG_PATH"):
            raise
        try:
            AppConfig.resolve_config_path()
        except FileNotFoundError:
            yield None
            return
        raise
    if config.database.backend == "memory":
        yield None
        return
    from deerflow.persistence.agents.sql import get_sync_sessionmaker
    from deerflow.persistence.tracing_profiles.sql import _lock_admission_fence

    with get_sync_sessionmaker(config.database.app_sync_sqlalchemy_url).begin() as session:
        _lock_admission_fence(session)
        yield session
