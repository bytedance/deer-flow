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
 * - ``setAttachments`` writes every change through, and submission retires
 *   the entries it sent in its ``onSent`` callback, which only fires once the
 *   send is dispatched (after any upload), so a failed upload keeps the chip
 *   and a document staged during the upload is kept for the next message.
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

function safeSetItem(storage: Storage, key: string, value: string): void {
  try {
    storage.setItem(key, value);
  } catch {
    // Storage can be unavailable or full. The caller keeps its in-memory state.
  }
}

function safeRemoveItem(storage: Storage, key: string): void {
  try {
    storage.removeItem(key);
  } catch {
    // Storage can be unavailable. The caller keeps its in-memory state.
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
  const key = storageKey(threadId);
  const pending = readStoredAttachments(storage, key);
  if (pending === null) {
    return;
  }
  const remaining = pending.filter(
    (candidate) => candidate.virtual_path !== attachment.virtual_path,
  );
  safeSetItem(storage, key, JSON.stringify([...remaining, attachment]));
}

/**
 * Read a thread's pending attachments **without consuming them**. Corrupt
 * payloads are dropped; the pre-list single-object payload shape is read as a
 * one-element list so a mid-session upgrade keeps the staged chip.
 */
export function readProjectAttachments(
  threadId: string,
): AttachProjectDocumentResult[] {
  return (
    readStoredAttachments(safeSessionStorage(), storageKey(threadId)) ?? []
  );
}

function readStoredAttachments(
  storage: Storage | null,
  key: string,
): AttachProjectDocumentResult[] | null {
  if (!storage) {
    return null;
  }
  let raw: string | null;
  try {
    raw = storage.getItem(key);
  } catch {
    // The list is unknown. Mutating callers must leave the stored value intact.
    return null;
  }
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
  safeRemoveItem(storage, key);
  return [];
}

/**
 * Drop the given attachments from a thread's pending list, keeping any staged
 * since. For a send dispatched after its composer has unmounted or moved on to
 * another thread: that send carries only what it captured, so documents
 * attached to the thread meanwhile must stay for the next message.
 */
export function retireProjectAttachments(
  threadId: string,
  sent: readonly AttachProjectDocumentResult[],
): void {
  const storage = safeSessionStorage();
  if (!storage) {
    return;
  }
  const key = storageKey(threadId);
  const pending = readStoredAttachments(storage, key);
  if (pending === null) {
    return;
  }
  const sentPaths = new Set(sent.map((attachment) => attachment.virtual_path));
  const remaining = pending.filter(
    (attachment) => !sentPaths.has(attachment.virtual_path),
  );
  if (remaining.length === 0) {
    safeRemoveItem(storage, key);
  } else {
    safeSetItem(storage, key, JSON.stringify(remaining));
  }
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
  const loadedThreadRef = useRef<string | null>(null);

  useEffect(() => {
    const pending = readStoredAttachments(
      safeSessionStorage(),
      storageKey(threadId),
    );
    loadedThreadRef.current = pending === null ? null : threadId;
    pendingRef.current = pending ?? [];
    setAttachmentsState(pendingRef.current);
  }, [threadId]);

  const setAttachments = useCallback(
    (value: SetStateAction<AttachProjectDocumentResult[]>) => {
      const next =
        typeof value === "function" ? value(pendingRef.current) : value;
      pendingRef.current = next;
      const storage =
        loadedThreadRef.current === threadId ? safeSessionStorage() : null;
      if (storage) {
        if (next.length === 0) {
          safeRemoveItem(storage, storageKey(threadId));
        } else {
          safeSetItem(storage, storageKey(threadId), JSON.stringify(next));
        }
      }
      setAttachmentsState(next);
    },
    [threadId],
  );

  return [attachments, setAttachments] as const;
}
