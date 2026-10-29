import os

import pytest
from deerflow_extension_api.host_capabilities import HostCapabilityError


@pytest.mark.skipif(os.name != "posix", reason="POSIX publication contract")
def test_sqlite_single_gateway_lease_is_exclusive_and_recoverable(tmp_path):
    from deerflow.skills.mutations.topology import PublicationTopology

    first = PublicationTopology("sqlite", tmp_path)
    first.acquire()
    try:
        with pytest.raises(HostCapabilityError, match="UNSUPPORTED_TOPOLOGY"):
            PublicationTopology("sqlite", tmp_path).acquire()
    finally:
        first.close()
    second = PublicationTopology("sqlite", tmp_path)
    second.acquire()
    second.close()


@pytest.mark.parametrize("backend", ["memory", "other"])
def test_unsupported_backend_fails_closed(tmp_path, backend):
    from deerflow.skills.mutations.topology import PublicationTopology

    with pytest.raises(HostCapabilityError, match="UNSUPPORTED_TOPOLOGY"):
        PublicationTopology(backend, tmp_path).acquire()


def test_sync_journal_uses_full_durability(tmp_path):
    from deerflow.skills.mutations.topology import mutation_session_factory

    engine, sessions = mutation_session_factory(f"sqlite:///{tmp_path / 'journal.db'}")
    try:
        with sessions() as session:
            from sqlalchemy import text

            assert session.scalar(text("PRAGMA synchronous")) == 2
            assert session.scalar(text("PRAGMA foreign_keys")) == 1
    finally:
        engine.dispose()
