"""Encrypted immutable drafts, with atomic one-attempt SMTP submission receipts."""

import json
import uuid
from contextlib import contextmanager

from .mail_sender import AliMailSender, normalize_message
from .providers import EnterpriseError
from .store import EnterpriseStore


class MailOutboxStore(EnterpriseStore):
    @contextmanager
    def _outbox_db(self):
        with self._enterprise_db() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS enterprise_mail_drafts ("
                "id TEXT PRIMARY KEY, owner TEXT NOT NULL, account_id TEXT NOT NULL, payload BLOB NOT NULL, "
                "status TEXT NOT NULL DEFAULT 'draft', result TEXT, message_id TEXT NOT NULL, "
                "created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )
            db.execute("CREATE INDEX IF NOT EXISTS ix_mail_draft_owner ON enterprise_mail_drafts(owner,created_at)")
            db.commit()
            yield db

    def _unpack(self, db, row):
        if row is None:
            raise EnterpriseError("draft_not_found")
        try:
            owner, draft_id, payload = json.loads(self._cipher(db).decrypt(row["payload"]))
            if owner != row["owner"] or draft_id != row["id"]:
                raise ValueError("scope")
        except Exception:
            raise EnterpriseError("credential_unavailable") from None
        return {**payload, "id": row["id"], "account_id": row["account_id"], "status": row["status"], "message_id": row["message_id"], "created_at": row["created_at"], "result": json.loads(row["result"]) if row["result"] else None}

    def create_draft(self, owner, account_id, payload):
        draft_id = uuid.uuid4().hex
        message_id = f"<deerflow.{draft_id}@{payload['sender'].split('@', 1)[1]}>"
        with self._outbox_db() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT COUNT(*) FROM enterprise_mail_drafts WHERE owner=? AND status='draft'", (owner,)).fetchone()[0] >= 100:
                raise EnterpriseError("mail_drafts_full")
            encrypted = self._cipher(db).encrypt(json.dumps([owner, draft_id, payload], ensure_ascii=False).encode("utf-8"))
            db.execute("INSERT INTO enterprise_mail_drafts(id,owner,account_id,payload,message_id) VALUES (?,?,?,?,?)", (draft_id, owner, account_id, encrypted, message_id))
            return self._unpack(db, db.execute("SELECT * FROM enterprise_mail_drafts WHERE id=?", (draft_id,)).fetchone())

    def draft(self, owner, draft_id):
        with self._outbox_db() as db:
            return self._unpack(db, db.execute("SELECT * FROM enterprise_mail_drafts WHERE id=? AND owner=?", (draft_id, owner)).fetchone())

    def drafts(self, owner):
        with self._outbox_db() as db:
            return [self._unpack(db, row) for row in db.execute("SELECT * FROM enterprise_mail_drafts WHERE owner=? ORDER BY created_at DESC,rowid DESC LIMIT 50", (owner,))]

    def claim(self, owner, draft_id):
        with self._outbox_db() as db:
            db.execute("BEGIN IMMEDIATE")
            draft = self._unpack(db, db.execute("SELECT * FROM enterprise_mail_drafts WHERE id=? AND owner=?", (draft_id, owner)).fetchone())
            if draft["status"] != "draft":
                return draft, False
            if not db.execute("SELECT 1 FROM enterprise_targets WHERE id=? AND owner=? AND enabled=1 AND provider='alimail'", (draft["account_id"], owner)).fetchone():
                raise EnterpriseError("target_not_found")
            recent = db.execute("SELECT COUNT(*) FROM enterprise_mail_drafts WHERE owner=? AND status NOT IN ('draft','discarded') AND updated_at>=datetime('now','-1 minute')", (owner,)).fetchone()[0]
            if recent >= 20:
                raise EnterpriseError("rate_limited")
            db.execute("UPDATE enterprise_mail_drafts SET status='sending',updated_at=CURRENT_TIMESTAMP WHERE id=? AND owner=?", (draft_id, owner))
            draft["status"] = "sending"
            return draft, True

    def finish(self, owner, draft_id, result):
        with self._outbox_db() as db:
            db.execute("UPDATE enterprise_mail_drafts SET status=?,result=?,updated_at=CURRENT_TIMESTAMP WHERE id=? AND owner=? AND status='sending'", (result["status"], json.dumps(result), draft_id, owner))
        return self.draft(owner, draft_id)

    def discard(self, owner, draft_id):
        with self._outbox_db() as db:
            db.execute("UPDATE enterprise_mail_drafts SET status='discarded',updated_at=CURRENT_TIMESTAMP WHERE id=? AND owner=? AND status='draft'", (draft_id, owner))
        return self.draft(owner, draft_id)


class MailOutboxService:
    def __init__(self, store, *, sender=None):
        self.store = store
        self.sender = sender or AliMailSender()

    def _credentials(self, owner, account_id):
        target = self.store.target(owner, account_id)
        if target["provider"] != "alimail":
            raise EnterpriseError("target_not_found")
        try:
            return json.loads(self.store.secret(owner, account_id))
        except (ValueError, TypeError):
            raise EnterpriseError("credential_unavailable") from None

    def draft(self, owner, account_id, payload):
        credentials = self._credentials(owner, account_id)
        return self.store.create_draft(owner, account_id, normalize_message(credentials["email"], payload))

    def send(self, owner, draft_id):
        # The exact stored content is immutable; the caller only confirms its ID.
        draft, claimed = self.store.claim(owner, draft_id)
        if not claimed:
            return draft
        try:
            credentials = self._credentials(owner, draft["account_id"])
        except EnterpriseError as exc:
            result = {"status": "failed", "error": exc.code, "accepted": [], "refused": []}
        else:
            try:
                result = self.sender.send(credentials, draft, draft["message_id"])
            except Exception:
                # Unexpected failure after a claim is conservatively ambiguous.
                result = {"status": "unknown", "error": "mail_send_unknown", "accepted": [], "refused": []}
        return self.store.finish(owner, draft_id, result)
