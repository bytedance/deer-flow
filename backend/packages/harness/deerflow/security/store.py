"""Single-node private storage. This directory must never be mounted into sandboxes."""

import json
import os
import sqlite3
import tempfile
from contextlib import contextmanager
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from deerflow.config.paths import get_paths
from deerflow.security.groups import EFFECTIVE_GRANTS_SQL, GroupPermissions, initialize_group_schema
from deerflow.security.user_profile import normalize_nickname


class UserSecurityStore(GroupPermissions):
    def __init__(self, root: str | Path | None = None):
        self.root = Path(root) if root else get_paths().base_dir / "security"

    @contextmanager
    def _db(self):
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        db_path = self.root / "users.db"
        db = sqlite3.connect(db_path, timeout=10)
        try:
            db.execute("PRAGMA foreign_keys=ON")
            os.chmod(db_path, 0o600)
            db.execute("CREATE TABLE IF NOT EXISTS grants (user_id TEXT, resource TEXT, target TEXT, PRIMARY KEY(user_id, resource, target))")
            db.execute("CREATE TABLE IF NOT EXISTS credentials (user_id TEXT, server TEXT, ciphertext BLOB NOT NULL, PRIMARY KEY(user_id, server))")
            db.execute("CREATE TABLE IF NOT EXISTS audit (at TEXT DEFAULT CURRENT_TIMESTAMP, actor TEXT, action TEXT, user_id TEXT, target TEXT)")
            db.execute("CREATE TABLE IF NOT EXISTS user_profiles (user_id TEXT PRIMARY KEY, nickname TEXT)")
            initialize_group_schema(db)
            db.commit()
            yield db
            db.commit()
        finally:
            db.close()

    def get_nickname(self, user_id: str) -> str | None:
        self._validate(user_id, "tool", "account_profile")
        with self._db() as db:
            row = db.execute("SELECT nickname FROM user_profiles WHERE user_id=?", (user_id,)).fetchone()
            return row[0] if row else None

    def set_nickname(self, user_id: str, nickname: str | None) -> str | None:
        self._validate(user_id, "tool", "account_profile")
        nickname = normalize_nickname(nickname)
        with self._db() as db:
            db.execute("INSERT INTO user_profiles(user_id,nickname) VALUES (?,?) ON CONFLICT(user_id) DO UPDATE SET nickname=excluded.nickname", (user_id, nickname))
        return nickname

    def _cipher(self, db, *, create=False):
        key_path = self.root / "master.key"
        if not key_path.exists():
            if not create or db.execute("SELECT 1 FROM credentials LIMIT 1").fetchone():
                raise RuntimeError("Personal credential encryption key is missing; restore the original key")
            # Caller owns a SQLite IMMEDIATE transaction: first writers across
            # processes cannot generate different keys. Publish a complete file.
            fd, temp = tempfile.mkstemp(dir=self.root, prefix=".key-")
            try:
                with os.fdopen(fd, "wb") as output:
                    output.write(Fernet.generate_key())
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(temp, key_path)
            finally:
                if os.path.exists(temp):
                    os.unlink(temp)
        return Fernet(key_path.read_bytes())

    @staticmethod
    def _validate(user_id, resource, target):
        if not isinstance(user_id, str) or not user_id or len(user_id) > 255:
            raise ValueError("A valid user ID is required")
        if resource not in {"tool", "mcp_server", "sandbox", "skill"} or not isinstance(target, str) or not target or len(target) > 255:
            raise ValueError("Invalid grant resource or target")
        if "*" in target and not (resource == "sandbox" and target == "*"):
            raise ValueError("Tool grants must name an exact resource")

    def grants(self, user_id):
        with self._db() as db:
            return set(db.execute(EFFECTIVE_GRANTS_SQL, {"user_id": user_id}).fetchall())

    def set_grant(self, user_id, resource, target, allowed, *, actor):
        self._validate(user_id, resource, target)
        with self._db() as db:
            if allowed:
                db.execute("DELETE FROM user_denies WHERE user_id=? AND resource=? AND target=?", (user_id, resource, target))
                db.execute("INSERT OR IGNORE INTO grants VALUES (?,?,?)", (user_id, resource, target))
            else:
                db.execute("DELETE FROM grants WHERE user_id=? AND resource=? AND target=?", (user_id, resource, target))
            db.execute("INSERT INTO audit(actor,action,user_id,target) VALUES (?,?,?,?)", (actor, "grant" if allowed else "revoke", user_id, f"{resource}:{target}"))

    def set_credential(self, user_id, server, credential):
        self._validate(user_id, "mcp_server", server)
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            payload = json.dumps([user_id, server, credential]).encode()
            encrypted = self._cipher(db, create=True).encrypt(payload)
            db.execute("INSERT OR REPLACE INTO credentials VALUES (?,?,?)", (user_id, server, encrypted))
            db.execute("INSERT INTO audit(actor,action,user_id,target) VALUES (?,?,?,?)", (user_id, "credential.set", user_id, server))

    def get_credential(self, user_id, server):
        with self._db() as db:
            row = db.execute("SELECT ciphertext FROM credentials WHERE user_id=? AND server=?", (user_id, server)).fetchone()
            if row is None:
                return None
            try:
                owner, source, value = json.loads(self._cipher(db).decrypt(row[0]))
                if owner != user_id or source != server:
                    raise ValueError("Credential scope mismatch")
                return value
            except (InvalidToken, ValueError, TypeError) as exc:
                raise RuntimeError("Personal credential could not be decrypted for this scope") from exc

    def credential_status(self, user_id):
        with self._db() as db:
            return [row[0] for row in db.execute("SELECT server FROM credentials WHERE user_id=? ORDER BY server", (user_id,))]

    def delete_credential(self, user_id, server):
        with self._db() as db:
            db.execute("DELETE FROM credentials WHERE user_id=? AND server=?", (user_id, server))
            db.execute("INSERT INTO audit(actor,action,user_id,target) VALUES (?,?,?,?)", (user_id, "credential.delete", user_id, server))
