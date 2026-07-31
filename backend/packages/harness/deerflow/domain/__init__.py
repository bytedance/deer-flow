"""Hexagonal inner ring: domain models, ports, and application services.

Every package under this namespace is one bounded context laid out as
`{model,ports,service}.py`. Code here has zero infrastructure
dependencies -- no sqlalchemy/fastapi/pydantic, no `app.*`, and no
harness infrastructure modules (enforced in CI by
`tests/test_harness_domain_purity.py`). Adapters implementing the ports
live in `app/adapters/{context}/`; wiring happens only in the composition
root, `app/composition.py::build_domain_services`.
"""
