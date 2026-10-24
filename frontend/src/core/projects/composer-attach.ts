import type { SetStateAction } from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useWorkspaceLifetime } from "@/core/workspaces/context";
import {
  captureWorkspaceRequestScope,
  type WorkspaceRequestScope,
} from "@/core/workspaces/request-scope";

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

export interface ProjectAttachmentStore {
  isActive(): boolean;
  read(threadId: string): AttachProjectDocumentResult[];
  write(threadId: string, attachments: AttachProjectDocumentResult[]): void;
  stage(threadId: string, attachment: AttachProjectDocumentResult): void;
  retire(threadId: string, sent: readonly AttachProjectDocumentResult[]): void;
}

function attachmentStore(
  scope?: WorkspaceRequestScope,
): ProjectAttachmentStore {
  const captured = scope ? captureWorkspaceRequestScope(scope) : undefined;
  const isActive = () => !captured?.signal.aborted;
  const keyFor = (threadId: string) =>
    captured
      ? `${STORAGE_KEY_PREFIX}v1.${JSON.stringify([captured.actorUserId, captured.workspaceId, threadId])}`
      : `${STORAGE_KEY_PREFIX}${threadId}`;
  const read = (threadId: string): AttachProjectDocumentResult[] => {
    if (!isActive()) return [];
    const storage = safeSessionStorage();
    if (!storage) return [];
    const key = keyFor(threadId);
    const raw = storage.getItem(key);
    if (raw === null) return [];
    try {
      const parsed: unknown = JSON.parse(raw);
      if (Array.isArray(parsed)) return parsed.filter(isAttachment);
      if (isAttachment(parsed)) return [parsed];
    } catch {
      /* Corrupt records are dropped within this namespace only. */
    }
    storage.removeItem(key);
    return [];
  };
  const write = (
    threadId: string,
    attachments: AttachProjectDocumentResult[],
  ) => {
    if (!isActive()) return;
    const storage = safeSessionStorage();
    if (!storage) return;
    const key = keyFor(threadId);
    if (attachments.length === 0) storage.removeItem(key);
    else storage.setItem(key, JSON.stringify(attachments));
  };
  return Object.freeze({
    isActive,
    read,
    write,
    stage(threadId: string, attachment: AttachProjectDocumentResult) {
      if (!isActive()) return;
      const pending = read(threadId).filter(
        (item) => item.virtual_path !== attachment.virtual_path,
      );
      write(threadId, [...pending, attachment]);
    },
    retire(threadId: string, sent: readonly AttachProjectDocumentResult[]) {
      if (!isActive()) return;
      const sentPaths = new Set(sent.map((item) => item.virtual_path));
      write(
        threadId,
        read(threadId).filter((item) => !sentPaths.has(item.virtual_path)),
      );
    },
  });
}
const legacyAttachments = attachmentStore();

/** Legacy unscoped drafts retain their existing keys and are never adopted. */
export function stageProjectAttachment(
  threadId: string,
  attachment: AttachProjectDocumentResult,
): void {
  legacyAttachments.stage(threadId, attachment);
}
export function readProjectAttachments(
  threadId: string,
): AttachProjectDocumentResult[] {
  return legacyAttachments.read(threadId);
}
export function retireProjectAttachments(
  threadId: string,
  sent: readonly AttachProjectDocumentResult[],
): void {
  legacyAttachments.retire(threadId, sent);
}

/** Persistent per actor/workspace; expired handles cannot read or modify it. */
export function createWorkspaceProjectAttachmentStore(
  scope: WorkspaceRequestScope,
): ProjectAttachmentStore {
  return attachmentStore(scope);
}
export function useProjectAttachmentStore(): ProjectAttachmentStore {
  const lifetime = useWorkspaceLifetime();
  return useMemo(
    () =>
      lifetime
        ? createWorkspaceProjectAttachmentStore(lifetime.scope)
        : legacyAttachments,
    [lifetime],
  );
}

/** Read without consuming; a successful send retires only the files it sent. */
export function useStagedProjectAttachments(threadId: string) {
  const store = useProjectAttachmentStore();
  const [attachments, setAttachmentsState] = useState<
    AttachProjectDocumentResult[]
  >([]);
  const pendingRef = useRef<AttachProjectDocumentResult[]>([]);
  const identity = useMemo(
    () => ({ threadId, store, mounted: true }),
    [threadId, store],
  );
  const current = useRef(identity);
  current.current = identity;
  useEffect(() => {
    identity.mounted = true;
    const pending = store.read(threadId);
    pendingRef.current = pending;
    setAttachmentsState(pending);
    return () => {
      identity.mounted = false;
    };
  }, [identity, store, threadId]);
  const setAttachments = useCallback(
    (value: SetStateAction<AttachProjectDocumentResult[]>) => {
      if (
        !identity.mounted ||
        current.current !== identity ||
        !store.isActive()
      )
        return;
      const next =
        typeof value === "function" ? value(pendingRef.current) : value;
      if (
        !identity.mounted ||
        current.current !== identity ||
        !store.isActive()
      )
        return;
      pendingRef.current = next;
      store.write(threadId, next);
      setAttachmentsState(next);
    },
    [identity, store, threadId],
  );
  return [attachments, setAttachments] as const;
}
