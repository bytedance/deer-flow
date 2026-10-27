"""Single-node private SQLite store, sharing the existing credential key.

All methods are synchronous and must run in a worker thread. This is not part
of the application ORM database; its schema follows UserSecurityStore.
"""

import hashlib
import json
import sqlite3
import uuid
from contextlib import contextmanager

from deerflow.security.store import UserSecurityStore

from .providers import EnterpriseError, WeComWebhook


class EnterpriseStore(UserSecurityStore):
    @contextmanager
    def _enterprise_db(self):
        with self._db() as db:
            db.row_factory = sqlite3.Row
            db.execute("CREATE TABLE IF NOT EXISTS enterprise_targets (id TEXT PRIMARY KEY, owner TEXT NOT NULL, name TEXT NOT NULL, provider TEXT NOT NULL, secret BLOB NOT NULL, enabled INTEGER NOT NULL DEFAULT 1, UNIQUE(owner,name))")
            db.execute(
                "CREATE TABLE IF NOT EXISTS enterprise_deliveries (id TEXT PRIMARY KEY, owner TEXT NOT NULL, "
                "request_key TEXT NOT NULL, target_id TEXT NOT NULL, target_name TEXT NOT NULL, digest TEXT NOT NULL, "
                "status TEXT NOT NULL, error TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(owner,request_key))"
            )
            db.execute("CREATE INDEX IF NOT EXISTS ix_enterprise_delivery_owner ON enterprise_deliveries(owner,created_at)")
            db.commit()
            yield db

    @staticmethod
    def _public(row):
        return {"id": row["id"], "name": row["name"], "provider": row["provider"], "enabled": bool(row["enabled"])}

    def create_target(self, owner, name, provider, secret):
        if provider != "wecom_webhook":
            raise EnterpriseError("unsupported_provider")
        WeComWebhook.validate_secret(secret)
        return self._create_target(owner, name, provider, secret)

    def create_mail_account(self, owner, name, credentials):
        from .mail import validate_account

        validate_account(credentials)
        return self._create_target(owner, name, "alimail", json.dumps(credentials))

    def _create_target(self, owner, name, provider, secret):
        name = name.strip()
        if not name or len(name) > 80:
            raise EnterpriseError("invalid_name")
        target_id = uuid.uuid4().hex
        try:
            with self._enterprise_db() as db:
                db.execute("BEGIN IMMEDIATE")
                if not (self.root / "master.key").exists() and db.execute("SELECT 1 FROM enterprise_targets LIMIT 1").fetchone():
                    raise EnterpriseError("credential_unavailable")
                encrypted = self._cipher(db, create=True).encrypt(json.dumps([owner, target_id, secret]).encode("utf-8"))
                db.execute("INSERT INTO enterprise_targets(id,owner,name,provider,secret) VALUES (?,?,?,?,?)", (target_id, owner, name, provider, encrypted))
        except sqlite3.IntegrityError:
            raise EnterpriseError("duplicate_name") from None
        return self.target(owner, target_id)

    def list_targets(self, owner, *, provider="wecom_webhook"):
        with self._enterprise_db() as db:
            return [self._public(row) for row in db.execute("SELECT * FROM enterprise_targets WHERE owner=? AND provider=? ORDER BY name", (owner, provider))]

    def target(self, owner, target_id):
        with self._enterprise_db() as db:
            row = db.execute("SELECT * FROM enterprise_targets WHERE id=? AND owner=?", (target_id, owner)).fetchone()
            if row is None:
                raise EnterpriseError("target_not_found")
            return self._public(row)

    def secret(self, owner, target_id):
        with self._enterprise_db() as db:
            row = db.execute("SELECT * FROM enterprise_targets WHERE id=? AND owner=? AND enabled=1", (target_id, owner)).fetchone()
            if row is None:
                raise EnterpriseError("target_not_found")
            try:
                identity, target, secret = json.loads(self._cipher(db).decrypt(row["secret"]))
                if identity != owner or target != target_id:
                    raise ValueError("scope")
            except Exception:
                raise EnterpriseError("credential_unavailable") from None
            return secret

    def delete_target(self, owner, target_id):
        with self._enterprise_db() as db:
            db.execute("DELETE FROM enterprise_targets WHERE id=? AND owner=?", (target_id, owner))

    def reserve(self, owner, target, content, request_key):
        digest = hashlib.sha256(json.dumps([target["id"], content], ensure_ascii=False).encode("utf-8")).hexdigest()
        with self._enterprise_db() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute("SELECT * FROM enterprise_deliveries WHERE owner=? AND request_key=?", (owner, request_key)).fetchone()
            if previous:
                if previous["digest"] != digest:
                    raise EnterpriseError("idempotency_conflict")
                return dict(previous), False
            count = db.execute("SELECT COUNT(*) FROM enterprise_deliveries WHERE owner=? AND target_id=? AND created_at>=datetime('now','-1 minute')", (owner, target["id"])).fetchone()[0]
            if count >= 20:
                raise EnterpriseError("rate_limited")
            delivery_id = uuid.uuid4().hex
            db.execute("INSERT INTO enterprise_deliveries(id,owner,request_key,target_id,target_name,digest,status) VALUES (?,?,?,?,?,?,?)", (delivery_id, owner, request_key, target["id"], target["name"], digest, "sending"))
            return dict(db.execute("SELECT * FROM enterprise_deliveries WHERE id=?", (delivery_id,)).fetchone()), True

    def finish(self, owner, delivery_id, status, error=None):
        with self._enterprise_db() as db:
            db.execute("UPDATE enterprise_deliveries SET status=?,error=? WHERE id=? AND owner=? AND status='sending'", (status, error, delivery_id, owner))

    def deliveries(self, owner):
        with self._enterprise_db() as db:
            rows = db.execute("SELECT id,target_name,status,error,created_at FROM enterprise_deliveries WHERE owner=? ORDER BY created_at DESC,id DESC LIMIT 100", (owner,))
            return [dict(row) for row in rows]
