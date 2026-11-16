"use client";

import type { Message } from "@langchain/langgraph-sdk";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import type { ArtifactSelectionEdit } from "@/core/artifacts/selection";
import {
  appendSidecarReference,
  buildMessageSidecarContext,
  getNextSidecarOpenState,
  type SidecarContext,
  type SidecarReferenceStateItem,
} from "@/core/sidecar";
import { findLatestSidecarThread } from "@/core/sidecar/api";
import type { ThreadStreamOptions } from "@/core/threads/hooks";

export type SidecarReference = SidecarReferenceStateItem;

type SidecarContextValue = {
  artifactEdit: ArtifactSelectionEdit | null;
  beginArtifactEdit: (edit: ArtifactSelectionEdit) => void;
  clearArtifactEdit: (id?: string) => void;
  open: boolean;
  /**
   * An incognito chat leaves no persistent side thread, so every path that
   * would create or open one is a no-op. Quoting into the main composer
   * (``addContextToConversation``) still works: that text rides the current
   * message and dies with the thread.
   */
  disabled: boolean;
  activeReferences: SidecarReference[];
  conversationQuotes: SidecarReference[];
  parentThreadId: string;
  context: ThreadStreamOptions["context"];
  setContext: (context: ThreadStreamOptions["context"]) => void;
  isMock?: boolean;
  sidecarThreadId: string | null;
  setSidecarThreadId: (threadId: string | null) => void;
  restoreSidecarThread: (options?: {
    force?: boolean;
  }) => Promise<string | null>;
  addContextToConversation: (context: SidecarContext) => void;
  clearConversationQuotes: (ids?: number[]) => void;
  clearActiveReferences: () => void;
  openSidecar: () => void;
  openContext: (context: SidecarContext) => void;
  openSelectedText: (
    message: Message,
    selectedText: string,
    displayIndex?: number,
  ) => void;
  close: () => void;
};

const SidecarContextObject = createContext<SidecarContextValue | null>(null);

export function SidecarProvider({
  children,
  parentThreadId,
  context,
  isMock,
  disabled = false,
}: {
  children: ReactNode;
  parentThreadId: string;
  context: ThreadStreamOptions["context"];
  isMock?: boolean;
  /** Incognito chats disable the side thread; quote-to-composer still works. */
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [artifactEdit, setArtifactEdit] =
    useState<ArtifactSelectionEdit | null>(null);
  const clearArtifactEdit = useCallback(
    (id?: string) => {
      if (id && artifactEdit?.id !== id) return;
      setArtifactEdit(null);
      setActiveReferences((references) =>
        references.filter(
          (reference) => reference.context !== artifactEdit?.context,
        ),
      );
    },
    [artifactEdit],
  );
  const [activeReferences, setActiveReferences] = useState<SidecarReference[]>(
    [],
  );
  const [sidecarThreadId, setSidecarThreadId] = useState<string | null>(null);
  const [sidecarContext, setSidecarContext] =
    useState<ThreadStreamOptions["context"]>(context);
  const [conversationQuotes, setConversationQuotes] = useState<
    SidecarReference[]
  >([]);
  const referenceIdRef = useRef(0);
  const parentThreadIdRef = useRef(parentThreadId);
  const sidecarThreadIdRef = useRef<string | null>(null);
  const restoreRequestRef = useRef<{
    parentThreadId: string;
    promise: Promise<string | null>;
  } | null>(null);

  const updateSidecarThreadId = useCallback((threadId: string | null) => {
    sidecarThreadIdRef.current = threadId;
    setSidecarThreadId(threadId);
  }, []);

  const createReference = useCallback((nextContext: SidecarContext) => {
    referenceIdRef.current += 1;
    return {
      id: referenceIdRef.current,
      context: nextContext,
    };
  }, []);

  useEffect(() => {
    if (parentThreadIdRef.current === parentThreadId) {
      return;
    }
    parentThreadIdRef.current = parentThreadId;
    setOpen(false);
    setActiveReferences([]);
    setSidecarContext(context);
    updateSidecarThreadId(null);
    setConversationQuotes([]);
    setArtifactEdit(null);
  }, [context, parentThreadId, updateSidecarThreadId]);

  const restoreSidecarThread = useCallback(
    async (options?: { force?: boolean }) => {
      // A disabled side thread is never restored: querying would adopt a
      // thread the incognito chat must not have, and the trigger stays hidden
      // because the id never leaves null.
      if (disabled) {
        return null;
      }
      // A non-forced restore trusts the cached id; a forced restore always
      // re-queries the backend so a sidecar deleted elsewhere reconciles to
      // null instead of pointing the trigger at a dead thread (#3555).
      if (!options?.force && sidecarThreadIdRef.current) {
        return sidecarThreadIdRef.current;
      }

      const restoreRequest = restoreRequestRef.current;
      if (restoreRequest?.parentThreadId === parentThreadId) {
        return restoreRequest.promise;
      }

      const promise = findLatestSidecarThread({
        parentThreadId,
        isMock,
      })
        .then((thread) => {
          const threadId = thread?.thread_id ?? null;
          if (parentThreadIdRef.current !== parentThreadId) {
            return null;
          }
          // Reconcile the cache with the backend: adopt a freshly found
          // thread, and on a forced refresh clear a stale id when the backend
          // no longer has a matching sidecar thread.
          if (threadId) {
            if (!sidecarThreadIdRef.current) {
              updateSidecarThreadId(threadId);
            }
          } else if (options?.force && sidecarThreadIdRef.current) {
            updateSidecarThreadId(null);
          }
          return threadId;
        })
        .catch(() => null)
        .finally(() => {
          if (restoreRequestRef.current?.promise === promise) {
            restoreRequestRef.current = null;
          }
        });

      restoreRequestRef.current = {
        parentThreadId,
        promise,
      };

      return promise;
    },
    [disabled, isMock, parentThreadId, updateSidecarThreadId],
  );

  // Drop any side thread adopted before the chat turned incognito (for
  // example when an entry flow reuses the provider), so no trigger or panel
  // can point at a persistent thread from this conversation.
  useEffect(() => {
    if (!disabled) {
      return;
    }
    setOpen(false);
    setActiveReferences([]);
    updateSidecarThreadId(null);
  }, [disabled, updateSidecarThreadId]);

  useEffect(() => {
    void restoreSidecarThread();
  }, [restoreSidecarThread]);

  const openContext = useCallback(
    (nextContext: SidecarContext) => {
      if (disabled) {
        return;
      }
      const nextReference = createReference(nextContext);

      setActiveReferences(
        (references) =>
          getNextSidecarOpenState({
            open,
            sidecarThreadId,
            activeReferences: references,
            nextReference,
          }).activeReferences,
      );
      setOpen(true);
    },
    [createReference, disabled, open, sidecarThreadId],
  );

  const addContextToConversation = useCallback(
    (nextContext: SidecarContext) => {
      const nextReference = createReference(nextContext);
      setConversationQuotes((references) =>
        appendSidecarReference(references, nextReference),
      );
    },
    [createReference],
  );

  const beginArtifactEdit = useCallback(
    (edit: ArtifactSelectionEdit) => {
      setArtifactEdit(edit);
      openContext(edit.context);
    },
    [openContext],
  );

  const clearConversationQuotes = useCallback((ids?: number[]) => {
    if (!ids) {
      setConversationQuotes([]);
      return;
    }
    const idsToClear = new Set(ids);
    setConversationQuotes((quotes) =>
      quotes.filter((quote) => !idsToClear.has(quote.id)),
    );
  }, []);

  const clearActiveReferences = useCallback(() => {
    setActiveReferences([]);
  }, []);

  const openSidecar = useCallback(() => {
    if (disabled) {
      return;
    }
    setOpen(true);
  }, [disabled]);

  const openSelectedText = useCallback(
    (message: Message, selectedText: string, displayIndex?: number) => {
      const nextContext = buildMessageSidecarContext(message, displayIndex, {
        selectedText,
      });
      if (!nextContext) {
        return;
      }
      openContext(nextContext);
    },
    [openContext],
  );

  const close = useCallback(() => {
    setOpen(false);
  }, []);

  const value = useMemo<SidecarContextValue>(
    () => ({
      artifactEdit,
      beginArtifactEdit,
      clearArtifactEdit,
      open,
      disabled,
      activeReferences,
      conversationQuotes,
      parentThreadId,
      context: sidecarContext,
      setContext: setSidecarContext,
      isMock,
      sidecarThreadId,
      setSidecarThreadId: updateSidecarThreadId,
      restoreSidecarThread,
      addContextToConversation,
      clearConversationQuotes,
      clearActiveReferences,
      openSidecar,
      openContext,
      openSelectedText,
      close,
    }),
    [
      artifactEdit,
      beginArtifactEdit,
      clearArtifactEdit,
      activeReferences,
      addContextToConversation,
      clearActiveReferences,
      clearConversationQuotes,
      close,
      conversationQuotes,
      disabled,
      isMock,
      open,
      openContext,
      openSelectedText,
      openSidecar,
      parentThreadId,
      restoreSidecarThread,
      sidecarContext,
      sidecarThreadId,
      updateSidecarThreadId,
    ],
  );

  return (
    <SidecarContextObject.Provider value={value}>
      {children}
    </SidecarContextObject.Provider>
  );
}

export function useMaybeSidecar() {
  return useContext(SidecarContextObject);
}

export function useSidecar() {
  const context = useMaybeSidecar();
  if (!context) {
    throw new Error("useSidecar must be used within a SidecarProvider");
  }
  return context;
}
