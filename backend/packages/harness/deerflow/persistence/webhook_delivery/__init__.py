"""Shared inbound webhook dedupe table (issue #4120).

ORM model only; row writes/reads go through raw SQL in
``app.channels.dedupe_store.PostgresInboundDedupeStore``.
"""
