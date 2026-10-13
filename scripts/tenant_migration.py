#!/usr/bin/env python3
"""Offline paired attribution only; never upgrades schemas or activates tenants.

Operator-generated drain/backup receipts are required for every write and final
verification. M10 owns their physical collection and deployment validation.
Database URLs come from private environment variables, never command arguments.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import stat
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from ecs_executor.schema import SCHEMA_REVISION, require_schema
from ecs_executor.tenant_backfill import apply_workspace_attribution, plan_workspace_attribution
from sqlalchemy import create_engine

from deerflow.persistence.workspaces.backfill import BACKFILL_REVISION, apply_personal_backfill, export_native_workspace_bindings, plan_personal_backfill

_SHA = re.compile(r"[0-9a-f]{64}")
_NAME = re.compile(r"[a-z0-9][a-z0-9_.-]{0,100}")


def _encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _digest(value):
    return hashlib.sha256(_encoded(value)).hexdigest()


def _target(engine):
    url = engine.url
    if engine.dialect.name == "sqlite":
        if not url.database or url.database == ":memory:":
            raise ValueError("persistent maintenance database required")
        return {"dialect": "sqlite", "database": str(Path(url.database).resolve())}
    if engine.dialect.name == "postgresql" and url.host and url.database:
        return {"dialect": "postgresql", "host": url.host, "port": url.port or 5432, "database": url.database}
    raise ValueError("unsupported maintenance database target")


def target_fingerprint(native_engine, executor_engine):
    native, executor = _target(native_engine), _target(executor_engine)
    if native == executor:
        raise ValueError("native and executor require independent databases")
    # Include query configuration in the digest without exposing URLs/credentials.
    return _digest({"native": native, "executor": executor, "native_options": dict(native_engine.url.query), "executor_options": dict(executor_engine.url.query)})


def _directory(path):
    path = Path(path)
    if path.is_symlink():
        raise ValueError("private maintenance directory must not be a symlink")
    path = path.resolve(strict=True)
    info = path.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise ValueError("owned mode-0700 maintenance directory required")
    root = Path(__file__).resolve().parents[1]
    if path == root or root in path.parents:
        raise ValueError("maintenance evidence must remain outside checkout")
    return path


def _read(directory, name):
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        raise ValueError("invalid maintenance evidence filename")
    try:
        descriptor = os.open(directory / name, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        raise ValueError("required maintenance evidence is missing") from None
    with os.fdopen(descriptor, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size > 32 * 1024 * 1024:
            raise ValueError("private maintenance evidence has unsafe ownership or shape")
        data = stream.read()
    try:
        value = json.loads(data)
    except (UnicodeError, ValueError):
        raise ValueError("invalid maintenance evidence JSON") from None
    if not isinstance(value, dict):
        raise ValueError("maintenance evidence must be an object")
    return value, hashlib.sha256(data).hexdigest()


def _write(directory, name, value):
    descriptor = os.open(directory / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(_encoded(value))
        stream.flush()
        os.fsync(stream.fileno())
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


@contextmanager
def _lock(directory):
    descriptor = os.open(directory / "operation.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(descriptor)
        if info.st_uid != os.getuid() or not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600:
            raise ValueError("unsafe maintenance operation lock")
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(descriptor)


def _maintenance(directory, target):
    manifest, manifest_sha = _read(directory, "maintenance.json")
    if manifest.get("format") != "deerflow.tenant.maintenance.v1" or manifest.get("target_sha256") != target:
        raise ValueError("maintenance receipt belongs to another target")
    try:
        generation = manifest["generation"]
        if str(UUID(generation)) != generation:
            raise ValueError
        expires = datetime.fromisoformat(manifest["expires_at"])
        remaining = (expires - datetime.now(UTC)).total_seconds()
        if not 0 < remaining <= 86400:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise ValueError("maintenance generation or expiry is invalid") from None
    evidence = manifest.get("evidence")
    if not isinstance(evidence, dict) or set(evidence) != {"drain", "backup"}:
        raise ValueError("maintenance requires drain and backup evidence")
    for name, reference in evidence.items():
        if not isinstance(reference, dict) or set(reference) != {"file", "sha256"}:
            raise ValueError("invalid maintenance evidence reference")
        receipt, digest = _read(directory, reference["file"])
        if digest != reference["sha256"] or receipt.get("format") != "deerflow.tenant." + name + ".v1" or receipt.get("generation") != generation or receipt.get("target_sha256") != target:
            raise ValueError("maintenance evidence digest or binding changed")
        flags = ("admission_closed", "writers_stopped", "physical_stopped") if name == "drain" else ("restore_verified",)
        if any(receipt.get(flag) is not True for flag in flags):
            raise ValueError("maintenance evidence lacks stopped writers or restored backup")
        if name == "backup" and any(not isinstance(receipt.get(key), str) or not _SHA.fullmatch(receipt[key]) for key in ("native_sha256", "executor_sha256", "nas_manifest_sha256")):
            raise ValueError("maintenance backup evidence lacks pinned artifacts")
    return {"generation": generation, "target_sha256": target, "maintenance_sha256": manifest_sha}


def _receipt(directory, phase, binding):
    value, _ = _read(directory, phase + ".json")
    if value.get("format") != "deerflow.tenant.phase.v1" or value.get("phase") != phase or any(value.get(key) != expected for key, expected in binding.items()):
        raise ValueError("maintenance phase receipt binding changed")
    if value.get("native_revision") != BACKFILL_REVISION or value.get("executor_revision") != SCHEMA_REVISION:
        raise ValueError("maintenance phase revision changed")
    return value


def _current_native(native_engine, receipt):
    with native_engine.connect() as conn:
        bindings = export_native_workspace_bindings(conn)
        plan = plan_personal_backfill(conn)
    if _digest(bindings) != receipt["bindings_sha256"] or _digest(plan) != receipt["native_plan_sha256"]:
        raise ValueError("native ownership changed after maintenance receipt")
    return bindings


def run_phase(native_engine, executor_engine, directory, *, operation, phase):
    if operation not in ("plan", "apply", "verify") or phase not in ("native", "executor", "all"):
        raise ValueError("unsupported maintenance operation")
    directory = _directory(directory)
    target = target_fingerprint(native_engine, executor_engine)
    with _lock(directory):
        if operation == "plan" and phase == "native":
            with native_engine.connect() as conn:
                return plan_personal_backfill(conn)
        binding = _maintenance(directory, target)
        require_schema(executor_engine)
        base = {"format": "deerflow.tenant.phase.v1", **binding, "native_revision": BACKFILL_REVISION, "executor_revision": SCHEMA_REVISION}
        if operation == "apply" and phase == "native":
            if (directory / "native.json").exists():
                receipt = _receipt(directory, "native", binding)
                _current_native(native_engine, receipt)
                return receipt
            with native_engine.begin() as conn:
                result = apply_personal_backfill(conn)
                bindings = export_native_workspace_bindings(conn)
                plan = plan_personal_backfill(conn)
            receipt = {**base, "phase": "native", "result": result, "bindings": bindings, "bindings_sha256": _digest(bindings), "native_plan_sha256": _digest(plan)}
            _write(directory, "native.json", receipt)
            return receipt
        if not (directory / "native.json").exists():
            raise ValueError("completed native receipt required before executor phase")
        native = _receipt(directory, "native", binding)
        bindings = _current_native(native_engine, native)
        if operation == "plan" and phase == "executor":
            with executor_engine.connect() as conn:
                return plan_workspace_attribution(conn, bindings)
        if operation == "apply" and phase == "executor":
            if (directory / "executor.json").exists():
                receipt = _receipt(directory, "executor", binding)
            else:
                with executor_engine.begin() as conn:
                    result = apply_workspace_attribution(conn, bindings)
                receipt = {**base, "phase": "executor", "result": result, "bindings_sha256": native["bindings_sha256"]}
                _write(directory, "executor.json", receipt)
            _verify_executor(executor_engine, bindings, receipt)
            return receipt
        if operation == "verify" and phase == "all":
            if not (directory / "executor.json").exists():
                raise ValueError("completed executor receipt required for verification")
            executor = _receipt(directory, "executor", binding)
            _verify_executor(executor_engine, bindings, executor)
            return {
                **binding,
                "metadata_verified": True,
                "ready_for_activation": False,
                "pending_gates": ["nas_mapping", "runtime_authorization", "schema_aware_release"],
                "native_quarantined": len(native["result"]["quarantined"]),
                "executor_quarantined": len(executor["result"]["quarantined"]),
            }
        raise ValueError("plan/apply requires one explicit phase; verify requires all")


def _verify_executor(engine, bindings, receipt):
    with engine.connect() as conn:
        plan = plan_workspace_attribution(conn, bindings)
    if plan["jobs"] or plan["affinities"] or plan["bindings_sha256"] != receipt["bindings_sha256"] or plan["quarantined"] != receipt["result"]["quarantined"]:
        raise ValueError("executor metadata differs from completed maintenance receipt")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("plan", "apply", "verify"))
    parser.add_argument("--phase", required=True, choices=("native", "executor", "all"))
    parser.add_argument("--receipt-directory", required=True)
    args = parser.parse_args()
    engines = []
    try:
        for name in ("DEERFLOW_TENANT_NATIVE_URL", "DEERFLOW_TENANT_EXECUTOR_URL"):
            engines.append(create_engine(os.environ[name]))
        result = run_phase(*engines, args.receipt_directory, operation=args.operation, phase=args.phase)
        if args.operation == "plan":
            directory = _directory(args.receipt_directory)
            _write(directory, "plan-" + uuid4().hex + ".json", result)
        print(json.dumps({"operation": args.operation, "phase": args.phase, "completed": True, "ready_for_activation": False}))
        return 0
    except Exception:
        # Never print driver errors, URLs, ownership DTOs or private evidence.
        print("Tenant maintenance refused; retain private receipts and review prerequisites.")
        return 1
    finally:
        for engine in engines:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
