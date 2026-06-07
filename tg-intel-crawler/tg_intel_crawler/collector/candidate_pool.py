"""Candidate group pool — yaml-backed, status-machine, no Telethon."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable

import yaml

from tg_intel_crawler.collector.group_extractor import CandidateSignal


_MAX_SOURCES = 3
_VALID_STATUSES = ("pending", "approved", "rejected")
_VALID_VERDICTS = (
    "llm_approved_high",
    "llm_approved_medium",
    "llm_approved_low",
    "llm_rejected",
)


class CandidatePool:
    """Persistent pool of group candidates discovered from messages.

    Format on disk (yaml):
        candidates:
          <key>:
            invite_hash: str | null
            first_seen: iso8601
            last_seen: iso8601
            count: int
            status: pending | approved | rejected
            sources:
              - {group, msg_id, channel}   # at most 3, FIFO
    """

    def __init__(self, path: str):
        self._path = Path(path)
        self._candidates: dict[str, dict] = {}
        self._load()

    # ---------- public API ----------

    def merge(self, signals: Iterable[CandidateSignal]) -> None:
        """Fold signals into the pool. Rejected candidates stay rejected."""
        for sig in signals:
            self._merge_one(sig)

    def list_all(self, status: str | None = None) -> list[dict]:
        """Return list of candidate dicts (with ``key`` field), optionally
        filtered by status."""
        out: list[dict] = []
        for key, entry in self._candidates.items():
            if status is not None and entry.get("status") != status:
                continue
            out.append({"key": key, **entry})
        return out

    def approve(self, keys: Iterable[str]) -> list[str]:
        """Mark candidates as approved. Returns the keys that actually changed."""
        return self._set_status(keys, "approved")

    def reject(self, keys: Iterable[str]) -> list[str]:
        return self._set_status(keys, "rejected")

    def approved_links(self) -> list[str]:
        """Telegram links for approved candidates — feed straight to join_group."""
        out: list[str] = []
        for key, entry in self._candidates.items():
            if entry.get("status") != "approved":
                continue
            if entry.get("invite_hash"):
                out.append(f"https://t.me/+{entry['invite_hash']}")
            else:
                out.append(f"https://t.me/{key}")
        return out

    def pending_for_review(
        self,
        *,
        now: datetime,
        count_growth_factor: float = 2.0,
        stale_days: int = 30,
        force_rereview: bool = False,
    ) -> list[dict]:
        """Return pending candidates that need (or want) an LLM review.

        A candidate is selected if its status is ``pending`` AND any of:
        - never reviewed (no ``llm_verdict`` field), OR
        - ``count > reviewed_count * count_growth_factor`` (heat doubled), OR
        - ``now - reviewed_at > stale_days``, OR
        - ``force_rereview=True``.

        Note: re-review applies to ALL pending candidates including those
        previously stamped ``llm_rejected`` — see spec §4 互斥规则.
        """
        out: list[dict] = []
        stale_threshold = now - timedelta(days=stale_days)
        for key, entry in self._candidates.items():
            if entry.get("status") != "pending":
                continue
            verdict = entry.get("llm_verdict")
            if verdict is None or force_rereview:
                out.append({"key": key, **entry})
                continue

            reviewed_count = int(verdict.get("reviewed_count", 0))
            cur_count = int(entry.get("count", 0))
            if cur_count > reviewed_count * count_growth_factor:
                out.append({"key": key, **entry})
                continue

            reviewed_at_str = verdict.get("reviewed_at") or ""
            try:
                reviewed_at = datetime.fromisoformat(reviewed_at_str)
            except ValueError:
                reviewed_at = None
            if reviewed_at is None or reviewed_at < stale_threshold:
                out.append({"key": key, **entry})
        return out

    def set_llm_verdict(self, key: str, verdict: dict) -> None:
        """Attach an llm_verdict block to a candidate. Does NOT change status.

        Validates ``verdict["verdict"]`` against the closed set in spec §4.
        Unknown keys are silently no-op (so a stale verdict for a deleted
        candidate doesn't crash the run).
        """
        v_name = verdict.get("verdict")
        if v_name not in _VALID_VERDICTS:
            raise ValueError(f"invalid verdict: {v_name!r}")
        entry = self._candidates.get(key)
        if entry is None:
            return
        entry["llm_verdict"] = dict(verdict)

    def apply_llm_approvals(self) -> list[dict]:
        """Promote pending candidates with llm_approved_high/medium verdicts
        to status=approved. Returns a list of dicts:

            [{"key": str, "link": str, "verdict": str, "confidence": str}, ...]

        Caller is responsible for appending links to config.groups and
        deciding which (high vs medium) to feed into JoinThrottle.
        Idempotent — already-approved candidates are not returned again.
        """
        promoted: list[dict] = []
        for key, entry in self._candidates.items():
            if entry.get("status") != "pending":
                continue
            verdict = entry.get("llm_verdict") or {}
            v_name = verdict.get("verdict")
            if v_name not in ("llm_approved_high", "llm_approved_medium"):
                continue
            entry["status"] = "approved"
            link = (
                f"https://t.me/+{entry['invite_hash']}"
                if entry.get("invite_hash")
                else f"https://t.me/{key}"
            )
            promoted.append({
                "key": key,
                "link": link,
                "verdict": v_name,
                "confidence": verdict.get("confidence", ""),
            })
        return promoted

    def flush(self) -> None:
        """Persist current state to disk."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"candidates": self._candidates}
        with self._path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(payload, f, allow_unicode=True, sort_keys=True)

    # ---------- internals ----------

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = yaml.safe_load(self._path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            data = {}
        self._candidates = data.get("candidates") or {}

    def _merge_one(self, sig: CandidateSignal) -> None:
        key = sig.key  # already 'username' or '+invite_hash'
        seen_iso = sig.seen_at.isoformat()
        source = {
            "group": sig.source_group,
            "msg_id": sig.source_msg_id,
            "channel": sig.channel,
        }

        if key in self._candidates:
            entry = self._candidates[key]
            entry["count"] = int(entry.get("count", 0)) + 1
            # last_seen takes the max
            prev_last = entry.get("last_seen") or ""
            if seen_iso > prev_last:
                entry["last_seen"] = seen_iso
            # first_seen takes the min
            prev_first = entry.get("first_seen") or seen_iso
            if seen_iso < prev_first:
                entry["first_seen"] = seen_iso
            # sources: keep first N (FIFO), don't push past cap
            sources = entry.setdefault("sources", [])
            if len(sources) < _MAX_SOURCES:
                sources.append(source)
            # NB: status is NOT changed here — rejected stays rejected,
            # approved stays approved.
        else:
            self._candidates[key] = {
                "invite_hash": sig.invite_hash,
                "first_seen": seen_iso,
                "last_seen": seen_iso,
                "count": 1,
                "status": "pending",
                "sources": [source],
            }

    def _set_status(self, keys: Iterable[str], status: str) -> list[str]:
        if status not in _VALID_STATUSES:
            raise ValueError(f"invalid status: {status}")
        changed: list[str] = []
        for key in keys:
            entry = self._candidates.get(key)
            if entry is None:
                continue
            if entry.get("status") != status:
                entry["status"] = status
                changed.append(key)
        return changed
