"use client";

/**
 * Local persistence for the kb list (2026-09-01): a user-defined display
 * order behind drag-to-reorder, and the remembered last-opened library.
 * Both live in localStorage by design — the list is small and personal,
 * the backend keeps its created_at ordering as the cross-device source of
 * truth, and a stored order that a newer device never made simply falls
 * back to it.
 */
import { useCallback, useMemo, useState } from "react";

import type { KnowledgeBase } from "@/core/knowledge/types";

export const KB_ORDER_STORAGE_KEY = "deerflow.knowledge.kb-order.v1";
export const LAST_KB_STORAGE_KEY = "deerflow.knowledge.last-kb.v1";

function readStringArray(key: string): string[] | null {
  try {
    const raw = window.localStorage.getItem(key);
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return null;
    return parsed.filter((item): item is string => typeof item === "string");
  } catch {
    // Private mode / quota / garbage — ordering is a nicety, never a crash.
    return null;
  }
}

/** Remembered last-opened library; `null` when absent or unreadable. */
export function readLastKbId(): string | null {
  try {
    const raw = window.localStorage.getItem(LAST_KB_STORAGE_KEY);
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    return typeof parsed === "string" ? parsed : null;
  } catch {
    return null;
  }
}

export function writeLastKbId(kbId: string) {
  try {
    window.localStorage.setItem(LAST_KB_STORAGE_KEY, JSON.stringify(kbId));
  } catch {
    // Best effort only.
  }
}

/**
 * Server order plus the user's local reorder. Kbs whose ids appear in the
 * stored order lead, in that order; everyone else (new kbs, or the list on a
 * device that never reordered) trails in server order. `commitMove` splices
 * the dragged id into the drop target's slot and persists the result.
 */
export function useKbLocalOrder(kbs: KnowledgeBase[]): {
  ordered: KnowledgeBase[];
  commitMove: (sourceId: string, targetId: string) => void;
} {
  const [order, setOrder] = useState<string[]>(
    () => readStringArray(KB_ORDER_STORAGE_KEY) ?? [],
  );

  const ordered = useMemo(() => {
    if (order.length === 0) return kbs;
    const rank = new Map(order.map((id, index) => [id, index] as const));
    const known = kbs
      .filter((kbItem) => rank.has(kbItem.id))
      .sort((a, b) => rank.get(a.id)! - rank.get(b.id)!);
    const fresh = kbs.filter((kbItem) => !rank.has(kbItem.id));
    return [...known, ...fresh];
  }, [kbs, order]);

  const commitMove = useCallback(
    (sourceId: string, targetId: string) => {
      if (sourceId === targetId) return;
      const ids = ordered.map((kbItem) => kbItem.id);
      const from = ids.indexOf(sourceId);
      const to = ids.indexOf(targetId);
      if (from === -1 || to === -1) return;
      ids.splice(to, 0, ...ids.splice(from, 1));
      setOrder(ids);
      try {
        window.localStorage.setItem(KB_ORDER_STORAGE_KEY, JSON.stringify(ids));
      } catch {
        // In-memory order still applies for this session.
      }
    },
    [ordered],
  );

  return { ordered, commitMove };
}
