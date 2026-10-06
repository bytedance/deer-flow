"""Vector-space projection (spec 2026-08-15): reducers, fetcher, cache.

Projects the four Qdrant collections (one shared dense space) down to 2D/3D
coordinates for the knowledge-base vector-space tab. The reducer layer is
pure numpy math — no Qdrant, DB, or network access — so it is testable in
isolation and safe to run inside ``anyio.to_thread``.
"""
