import type { SetStateAction } from "react";
import { useCallback, useEffect, useRef, useState } from "react";

import type { AttachProjectDocumentResult } from "./types";

/**
 * Cross-route handoff for attach-to-thread (spec §9): the project page's
 * Documents tab stages the *completed* attachment here on success and
 * navigates to the target thread, where the composer shows the file as an
 * already-uploaded attachment. The handoff only ever carries a
 * server-confirmed ingestion result — never an in-flight upload — so the
 * composer receives a completed attachment only on success.
 *
 * The staged set is a per-thread pending LIST that persists until the
 * message is actually sent or the chip is explicitly removed:
 *
 * - Attaching a second document appends to the list (re-attaching the same
 *   document refreshes its entry), so navigating back to the project page
 *   between attaches cannot drop the earlier attachment.
 * - Mounting the composer only *reads* the list — nothing is consumed on
 *   mount, so a reload or a remount before submission keeps every chip.
 * - ``setAttachments`` writes every change through, and submission clears
 *   the list in its ``onSent`` callback, which only fires when the send
 *   genuinely proceeds.
 *
 * sessionStorage (not module memory) so the pending list also survives a
 * full page load of the target thread.
 */
const STORAGE_KEY_PREFIX = "deerflow.project-attachment.";

function storageKey(threadId: string): string {
  return `${STORAGE_KEY_PREFIX}${threadId}`;
}

function safeSessionStorage(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.sessionStorage;
  } catch {
    // Storage can be unavailable (privacy mode, sandboxed frame). The
    // handoff is best-effort — degrading to memory-only state.
    return null;
  }
}

function isAttachment(value: unknown): value is AttachProjectDocumentResult {
  return (
    value !== null &&
    typeof value === "object" &&
    "filename" in value &&
    "virtual_path" in value &&
    typeof (value as AttachProjectDocumentResult).filename === "string" &&
    typeof (value as AttachProjectDocumentResult).virtual_path === "string"
  );
}

/**
 * Stage one thread-confirmed attachment, appending it to that thread's
 * pending list. Re-staging the same document (same ``virtual_path``)
 * refreshes its entry instead of duplicating it.
 */
export function stageProjectAttachment(
  threadId: string,
  attachment: AttachProjectDocumentResult,
): void {
  const storage = safeSessionStorage();
  if (!storage) {
    return;
  }
  const pending = readProjectAttachments(threadId).filter(
    (candidate) => candidate.virtual_path !== attachment.virtual_path,
  );
  storage.setItem(
    storageKey(threadId),
    JSON.stringify([...pending, attachment]),
  );
}

/**
 * Read a thread's pending attachments **without consuming them**. Corrupt
 * payloads are dropped; the pre-list single-object payload shape is read as a
 * one-element list so a mid-session upgrade keeps the staged chip.
 */
export function readProjectAttachments(
  threadId: string,
): AttachProjectDocumentResult[] {
  const storage = safeSessionStorage();
  if (!storage) {
    return [];
  }
  const raw = storage.getItem(storageKey(threadId));
  if (raw === null) {
    return [];
  }
  try {
    const parsed = JSON.parse(raw) as unknown;
    if (Array.isArray(parsed)) {
      return parsed.filter(isAttachment);
    }
    if (isAttachment(parsed)) {
      return [parsed];
    }
  } catch {
    // Corrupt payload: drop it.
  }
  storage.removeItem(storageKey(threadId));
  return [];
}

/**
 * The current thread's pending attachments, held by the mounted composer.
 *
 * The list is loaded from storage on mount and on every thread change, and
 * every mutation is written back immediately, so unmounting (navigating to
 * the project page, reloading) never loses a pending chip. A Strict-Mode
 * effect replay re-reads the same list and re-applies the same state — there
 * is no consume step left to replay wrongly.
 *
 * The returned setter accepts the same value-or-updater shapes as
 * ``useState`` and is stable per thread.
 */
export function useStagedProjectAttachments(threadId: string) {
  const [attachments, setAttachmentsState] = useState<
    AttachProjectDocumentResult[]
  >([]);
  const pendingRef = useRef<AttachProjectDocumentResult[]>([]);

  useEffect(() => {
    const pending = readProjectAttachments(threadId);
    pendingRef.current = pending;
    setAttachmentsState(pending);
  }, [threadId]);

  const setAttachments = useCallback(
    (value: SetStateAction<AttachProjectDocumentResult[]>) => {
      const next =
        typeof value === "function" ? value(pendingRef.current) : value;
      pendingRef.current = next;
      const storage = safeSessionStorage();
      if (storage) {
        if (next.length === 0) {
          storage.removeItem(storageKey(threadId));
        } else {
          storage.setItem(storageKey(threadId), JSON.stringify(next));
        }
      }
      setAttachmentsState(next);
    },
    [threadId],
  );

  return [attachments, setAttachments] as const;
}
