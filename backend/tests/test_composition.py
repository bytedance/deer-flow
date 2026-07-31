"""Composition-root tests -- the rules the wiring itself owns.

``build_domain_services`` was extracted into a pure function precisely so
these rules are assertions instead of a comment inside the lifespan:
a ``database.backend: memory`` deployment gets no services (the dependency
providers translate that into 503).
"""

from app.composition import build_domain_services


class TestMemoryBackend:
    def test_no_sql_backend_means_no_services(self):
        services = build_domain_services(session_factory=None, run_store=object())
        assert services.feedback is None


class TestSqlBackend:
    def test_services_are_assembled(self):
        # A bare object suffices: the factory is only handed to adapters,
        # never called during assembly.
        services = build_domain_services(session_factory=object(), run_store=object())
        assert services.feedback is not None
