"""Offline, monotonic activation of PostgreSQL Run producer enforcement."""

from __future__ import annotations

import argparse
import asyncio
import sys


async def activate(*, config_path: str | None, cutover_id: str) -> None:
    from deerflow.config.app_config import AppConfig
    from deerflow.persistence.engine import close_engine, get_engine, get_session_factory, init_engine_from_config
    from deerflow.persistence.run.producer import activate_producer_fencing

    config = AppConfig.from_file(config_path)
    if config.database.backend != "postgres":
        raise RuntimeError("Producer cutover requires PostgreSQL")
    try:
        # Bootstrap the migrated schema, but never echo credential-bearing SQL.
        await init_engine_from_config(config.database.model_copy(update={"echo_sql": False}))
        # Bootstrap may have opened several pooled connections. The offline
        # session check must count external clients, not our own idle pool.
        await get_engine().dispose()
        await activate_producer_fencing(get_session_factory(), cutover_id=cutover_id)
    finally:
        await close_engine()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", help="Operator config.yaml (normal config resolution when omitted)")
    parser.add_argument("--cutover-id", required=True, help="Deployment ID; must match every Gateway's startup config")
    parser.add_argument("--all-gateways-stopped", required=True, action="store_true", help="Acknowledge that all Gateways and producers have stopped")
    args = parser.parse_args(argv)
    try:
        asyncio.run(activate(config_path=args.config, cutover_id=args.cutover_id))
    except Exception as exc:
        # Driver/config exceptions can contain credentials and config contents.
        print(f"Producer cutover refused ({type(exc).__name__}); verify migration, stopped clients, active Runs and cutover ID.", file=sys.stderr)
        return 1
    print("Producer fencing activated. Restart every Gateway with strict mode and the matching cutover ID.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
