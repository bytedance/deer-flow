# Storage adapter example

This is an independently installable synchronous SQLAlchemy library, not a Gateway
plugin or a replacement for core persistence/checkpointers. Keep models, migrations,
user identity and environment parsing in the consuming extension.

Providers own URL validation, engine construction and upsert syntax. Preserve
explicit backend selection, validated connection budgets, session ownership and
terminal disposal. Never replay writes after an uncertain socket timeout.
SQLite connections enable foreign keys/WAL and bounded busy waits.

Run `python -m pytest tests -q` after installing `.[mysql,test]`. Live tests use only
an explicitly configured disposable `STORAGE_TEST_MYSQL_URL`. Update README.md for
public API changes; do not add internal deployment information or credentials.
