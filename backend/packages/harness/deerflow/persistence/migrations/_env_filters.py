"""Object filters used by ``env.py`` to scope alembic to DeerFlow tables.

LangGraph checkpointer tables live in the same database but are owned by
LangGraph. Without this filter, ``alembic revision --autogenerate`` would
reflect them and emit spurious ``drop_table`` ops every revision.

Extensions that persist data follow the same shape: they own their own
``MetaData`` and their own migration chain, so their tables share the
database but are absent from ``Base.metadata``. ``register_extension_table_prefix``
lets an extension declare the prefix its tables share so this filter excludes
them too.

Which path this actually guards, since it is narrower than it looks:
``make migrate-rev`` is already safe by construction — ``_autogen_revision.py``
builds a throwaway SQLite from the migration chain and diffs against that, so
neither LangGraph's tables nor an extension's are ever reflected. What is not
safe is running ``alembic revision --autogenerate`` directly from this
directory, where ``alembic.ini`` points ``sqlalchemy.url`` at a real
``./data/deerflow.db``. That is the path both exclusions cover, and it is why
``LANGGRAPH_OWNED_TABLES`` exists despite the throwaway-DB script landing in
the same commit.

Kept in its own module (instead of inlined in ``env.py``) so it can be
unit-tested without dragging in alembic's import-time machinery.
"""

from __future__ import annotations

# Tables owned by LangGraph -- alembic must never propose DDL for them.
LANGGRAPH_OWNED_TABLES: frozenset[str] = frozenset(
    {
        "checkpoints",
        "checkpoint_blobs",
        "checkpoint_writes",
        "checkpoint_migrations",
    }
)


#: Table-name prefixes owned by loaded extensions. An extension brings its own
#: MetaData and its own migration chain, so its tables are absent from
#: Base.metadata; without this, autogenerate would reflect them and propose
#: dropping them.
EXTENSION_TABLE_PREFIXES: set[str] = set()


def _host_table_names() -> frozenset[str]:
    """Every table name the host itself owns.

    Imported on demand rather than at module scope: this module is
    deliberately kept import-light (see module docstring) so it stays
    unit-testable without dragging in the ORM's import graph unless a prefix
    is actually being registered.
    """
    import deerflow.persistence.models  # noqa: F401 - registers ORM tables onto Base.metadata
    from deerflow.persistence.base import Base

    return frozenset(Base.metadata.tables.keys())


def register_extension_table_prefix(prefix: str) -> None:
    """Declare a table-name prefix alembic must not propose DDL for.

    Fails loudly when the prefix would also match a host-owned table name
    (``str.startswith``, the same test ``_is_extension_owned`` uses below): a
    prefix like ``"run"`` would silently exclude the host's own ``runs`` and
    ``run_events`` tables from autogenerate, and that has to be caught here.
    An earlier design reasoned about a malicious prefix and left it at that;
    this guards against the far more likely case of an honest typo, which is
    exactly the failure mode this whole facility exists to prevent autogenerate
    from producing silently.
    """
    if not prefix:
        raise ValueError("extension table prefix must be a non-empty string")
    colliding = sorted(name for name in _host_table_names() if name.startswith(prefix))
    if colliding:
        raise ValueError(f"extension table_prefix {prefix!r} would hide host-owned table(s) {colliding!r} from alembic autogenerate; choose a prefix that is not a prefix of any host table name")
    EXTENSION_TABLE_PREFIXES.add(prefix)


def register_configured_extension_table_prefixes(config_path: str | None = None) -> tuple[str, ...]:
    """Register the prefixes declared by ``plugins:`` in ``config.yaml``.

    Alembic runs in its own process. ``make migrate-rev`` spawns
    ``scripts/_autogen_revision.py``, and a direct ``alembic revision`` runs
    from the migrations directory — neither starts a Gateway, so neither calls
    ``load_extensions()``. Registering only from there would leave
    ``EXTENSION_TABLE_PREFIXES`` empty in the one process that reads it, and
    the filter below would silently degrade to its LangGraph-only behaviour.

    Only the declaration is read. Extension code is never imported: a
    migration process must not execute third-party code, and the prefix is a
    plain string sitting in config. That is also why this parses the YAML
    directly instead of going through ``AppConfig`` — an unrelated validation
    error elsewhere in the file should not stop someone generating a revision.

    Entries whose ``table_prefix`` is absent, null, empty, or not a string are
    skipped rather than rejected, matching what the Gateway does with the same
    declaration: ``ExtensionSpec`` rejects them at config-load time, so this
    process would only be adding a second, worse-placed verdict.

    Returns the prefixes it registered, for the caller to log or assert on.
    """
    import yaml

    from deerflow.config.app_config import AppConfig

    try:
        path = AppConfig.resolve_config_path(config_path)
    except FileNotFoundError:
        # A clean checkout has no config.yaml, so there is nothing declared and
        # nothing to exclude. Not an error.
        return ()

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        # Refusing here is the point of the whole filter: if the declarations
        # cannot be read, the exclusion cannot be guaranteed, and a silently
        # unfiltered autogenerate is exactly the outcome this prevents.
        raise RuntimeError(f"could not read extension table prefixes from {path}: {exc}") from exc

    registered: list[str] = []
    for entry in raw.get("plugins") or []:
        if not isinstance(entry, dict):
            continue
        prefix = entry.get("table_prefix")
        if not isinstance(prefix, str) or not prefix:
            # Absent, null, empty, or the wrong type: nothing to exclude. This reader
            # parses raw YAML precisely so it never imports the extension, which
            # also means ``ExtensionSpec`` never validates what it sees -- so it
            # must skip whatever that model would reject (``min_length=1`` there)
            # instead of adjudicating it. Raising here would put the verdict in
            # the wrong process twice over: alembic is not where an operator
            # expects to hear that config.yaml is malformed, and Gateway startup
            # runs this same module through ``bootstrap_schema``, so a raise
            # would take the Gateway down with a message about migrations.
            continue
        register_extension_table_prefix(prefix)
        registered.append(prefix)
    return tuple(registered)


def _is_extension_owned(name: object) -> bool:
    return isinstance(name, str) and any(name.startswith(prefix) for prefix in EXTENSION_TABLE_PREFIXES)


def include_object(object_, name, type_, reflected, compare_to):  # noqa: ARG001
    """Returns False for any LangGraph-owned or extension-owned table, or for an
    index/constraint whose parent table is one of those. Returns True otherwise.

    Signature matches alembic's ``include_object`` callable contract:
    ``(object, name, type_, reflected, compare_to)``.
    """
    if type_ == "table" and (name in LANGGRAPH_OWNED_TABLES or _is_extension_owned(name)):
        return False
    parent_table = getattr(object_, "table", None)
    parent_name = getattr(parent_table, "name", None) if parent_table is not None else None
    if parent_name is not None and (parent_name in LANGGRAPH_OWNED_TABLES or _is_extension_owned(parent_name)):
        return False
    return True
