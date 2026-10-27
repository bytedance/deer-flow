"""Group membership and exact permission composition for the private store."""

import sqlite3
import unicodedata
from uuid import uuid4

EFFECTIVE_GRANTS_SQL = """
    SELECT resource,target FROM grants WHERE user_id=:user_id
    UNION
    SELECT g.resource,g.target FROM group_grants g
      JOIN group_members m ON m.group_id=g.group_id WHERE m.user_id=:user_id
    EXCEPT
    SELECT resource,target FROM user_denies WHERE user_id=:user_id
"""


def initialize_group_schema(db):
    db.execute("CREATE TABLE IF NOT EXISTS user_groups (id TEXT PRIMARY KEY, name TEXT NOT NULL, name_key TEXT NOT NULL UNIQUE)")
    db.execute("CREATE TABLE IF NOT EXISTS group_members (group_id TEXT REFERENCES user_groups(id) ON DELETE CASCADE, user_id TEXT NOT NULL, PRIMARY KEY(group_id,user_id))")
    db.execute("CREATE INDEX IF NOT EXISTS group_members_by_user ON group_members(user_id)")
    db.execute("CREATE TABLE IF NOT EXISTS group_grants (group_id TEXT REFERENCES user_groups(id) ON DELETE CASCADE, resource TEXT, target TEXT, PRIMARY KEY(group_id,resource,target))")
    db.execute("CREATE TABLE IF NOT EXISTS user_denies (user_id TEXT, resource TEXT, target TEXT, PRIMARY KEY(user_id,resource,target))")


class GroupPermissions:
    """Mixin sharing UserSecurityStore's transaction, validation and audit database."""

    @staticmethod
    def _group_name(name):
        if not isinstance(name, str) or any(unicodedata.category(char).startswith("C") for char in name):
            raise ValueError("Invalid group name")
        name = unicodedata.normalize("NFKC", name).strip()
        if not name or len(name) > 80:
            raise ValueError("Group name must contain 1–80 characters")
        return name, name.casefold()

    @staticmethod
    def _require_group(db, group_id):
        row = db.execute("SELECT id,name FROM user_groups WHERE id=?", (group_id,)).fetchone()
        if row is None:
            raise KeyError("Group not found")
        return {"id": row[0], "name": row[1]}

    @staticmethod
    def _group_audit(db, actor, action, group_id, user_id="", target=""):
        db.execute("INSERT INTO audit(actor,action,user_id,target) VALUES (?,?,?,?)", (actor, action, user_id, f"group:{group_id}:{target}"))

    def create_group(self, name, *, actor):
        name, key = self._group_name(name)
        group_id = str(uuid4())
        with self._db() as db:
            try:
                db.execute("INSERT INTO user_groups VALUES (?,?,?)", (group_id, name, key))
            except sqlite3.IntegrityError:
                raise ValueError("Group name already exists") from None
            self._group_audit(db, actor, "group.create", group_id, target=name)
        return {"id": group_id, "name": name, "member_count": 0}

    def rename_group(self, group_id, name, *, actor):
        name, key = self._group_name(name)
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            self._require_group(db, group_id)
            try:
                db.execute("UPDATE user_groups SET name=?,name_key=? WHERE id=?", (name, key, group_id))
            except sqlite3.IntegrityError:
                raise ValueError("Group name already exists") from None
            self._group_audit(db, actor, "group.rename", group_id, target=name)
            count = db.execute("SELECT count(*) FROM group_members WHERE group_id=?", (group_id,)).fetchone()[0]
        return {"id": group_id, "name": name, "member_count": count}

    def delete_group(self, group_id, *, actor):
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            self._require_group(db, group_id)
            db.execute("DELETE FROM user_groups WHERE id=?", (group_id,))
            self._group_audit(db, actor, "group.delete", group_id)

    def list_groups(self):
        with self._db() as db:
            rows = db.execute("SELECT g.id,g.name,count(m.user_id) FROM user_groups g LEFT JOIN group_members m ON m.group_id=g.id GROUP BY g.id ORDER BY g.name_key,g.id").fetchall()
            return [{"id": row[0], "name": row[1], "member_count": row[2]} for row in rows]

    def group_details(self, group_id):
        with self._db() as db:
            db.execute("BEGIN")
            group = self._require_group(db, group_id)
            group["members"] = [row[0] for row in db.execute("SELECT user_id FROM group_members WHERE group_id=? ORDER BY user_id", (group_id,))]
            group["grants"] = db.execute("SELECT resource,target FROM group_grants WHERE group_id=? ORDER BY resource,target", (group_id,)).fetchall()
            return group

    def set_member(self, group_id, user_id, member, *, actor):
        self._validate(user_id, "sandbox", "*")
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            self._require_group(db, group_id)
            if member:
                db.execute("INSERT OR IGNORE INTO group_members VALUES (?,?)", (group_id, user_id))
            else:
                db.execute("DELETE FROM group_members WHERE group_id=? AND user_id=?", (group_id, user_id))
            self._group_audit(db, actor, "group.member.add" if member else "group.member.remove", group_id, user_id=user_id)

    def set_group_grant(self, group_id, resource, target, allowed, *, actor):
        self._validate(group_id, resource, target)
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            self._require_group(db, group_id)
            if allowed:
                db.execute("INSERT OR IGNORE INTO group_grants VALUES (?,?,?)", (group_id, resource, target))
            else:
                db.execute("DELETE FROM group_grants WHERE group_id=? AND resource=? AND target=?", (group_id, resource, target))
            self._group_audit(db, actor, "group.grant" if allowed else "group.revoke", group_id, target=f"{resource}:{target}")

    def set_override(self, user_id, resource, target, mode, *, actor):
        self._validate(user_id, resource, target)
        if mode not in {"inherit", "allow", "deny"}:
            raise ValueError("Unknown permission mode")
        with self._db() as db:
            db.execute("DELETE FROM grants WHERE user_id=? AND resource=? AND target=?", (user_id, resource, target))
            db.execute("DELETE FROM user_denies WHERE user_id=? AND resource=? AND target=?", (user_id, resource, target))
            if mode == "allow":
                db.execute("INSERT INTO grants VALUES (?,?,?)", (user_id, resource, target))
            elif mode == "deny":
                db.execute("INSERT INTO user_denies VALUES (?,?,?)", (user_id, resource, target))
            db.execute("INSERT INTO audit(actor,action,user_id,target) VALUES (?,?,?,?)", (actor, "override." + mode, user_id, f"{resource}:{target}"))

    def grant_details(self, user_id):
        with self._db() as db:
            # One read transaction keeps sources and effective permissions consistent.
            db.execute("BEGIN")
            groups = db.execute("SELECT g.id,g.name FROM user_groups g JOIN group_members m ON m.group_id=g.id WHERE m.user_id=? ORDER BY g.name_key,g.id", (user_id,)).fetchall()
            return {
                "grants": sorted(db.execute(EFFECTIVE_GRANTS_SQL, {"user_id": user_id}).fetchall()),
                "direct_grants": db.execute("SELECT resource,target FROM grants WHERE user_id=? ORDER BY resource,target", (user_id,)).fetchall(),
                "denied": db.execute("SELECT resource,target FROM user_denies WHERE user_id=? ORDER BY resource,target", (user_id,)).fetchall(),
                "groups": [{"id": row[0], "name": row[1]} for row in groups],
            }
