"""Check the real asyncpg dialect's connection contract without a database."""

import pytest
from sqlalchemy.engine import make_url
from support.postgres import asyncpg_test_url


@pytest.mark.parametrize("scheme", ["postgres", "postgresql", "postgresql+asyncpg"])
@pytest.mark.parametrize("sslmode", [None, "disable", "allow", "prefer", "require", "verify-ca", "verify-full"])
def test_asyncpg_test_url_preserves_tls_credentials_and_other_options(scheme, sslmode):
    uri = f"{scheme}://user:p%40ss%2Fword@localhost:5432/deerflow_test?target_session_attrs=read-write&channel_binding=prefer"
    if sslmode is not None:
        uri += f"&sslmode={sslmode}"
    url = make_url(asyncpg_test_url(uri))
    _args, kwargs = url.get_dialect()().create_connect_args(url)
    assert url.drivername == "postgresql+asyncpg"
    assert kwargs["password"] == "p@ss/word"
    assert kwargs["target_session_attrs"] == "read-write"
    assert "sslmode" not in kwargs and "channel_binding" not in kwargs
    if sslmode is None:
        assert "ssl" not in kwargs
    else:
        assert kwargs["ssl"] == sslmode


@pytest.mark.parametrize("query", ["ssl=require", "ssl=require&sslmode=require"])
def test_asyncpg_test_url_preserves_explicit_ssl(query):
    url = make_url(asyncpg_test_url(f"postgresql://user:password@localhost/test?{query}"))
    _args, kwargs = url.get_dialect()().create_connect_args(url)
    assert kwargs["ssl"] == "require"


def test_asyncpg_test_url_rejects_conflicting_tls_options():
    with pytest.raises(ValueError, match="Conflicting ssl and sslmode"):
        asyncpg_test_url("postgresql://user:password@localhost/test?ssl=require&sslmode=disable")
