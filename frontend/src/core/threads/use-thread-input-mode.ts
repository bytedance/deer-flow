import { useQueryClient } from "@tanstack/react-query";
import {
  useCallback,
  useLayoutEffect,
  useMemo,
  useReducer,
  useRef,
  useState,
} from "react";
import { toast } from "sonner";

import type { InputMode } from "@/core/models/reasoning";
import type { LocalSettings } from "@/core/settings/local";

import { createThread, patchThreadMetadata } from "./api";
import {
  INFINITE_THREADS_QUERY_KEY_PREFIX,
  setThreadMetadataInCaches,
  useThreadMetadata,
} from "./hooks";

/** Only Chat changes the thread's file policy. Ordinary modes follow composer preferences. */
export function useThreadInputMode({
  threadId,
  preferred,
  isNewThread = false,
  isMock = false,
  restoring = false,
  projectId,
  projectUnavailable,
  agentName,
  userId,
}: {
  threadId: string | null;
  preferred: LocalSettings["context"];
  isNewThread?: boolean;
  isMock?: boolean;
  restoring?: boolean;
  projectId?: string | null;
  projectUnavailable?: string;
  agentName?: string;
  userId?: string;
}) {
  const queryClient = useQueryClient();
  const threadMetadata = useThreadMetadata(threadId, {
    enabled: !isNewThread && !isMock,
    isMock,
  });
  const materialized = !isMock && (!isNewThread || !!threadMetadata.data);
  const savedChat = threadMetadata.data?.metadata?.mode === "chat";
  const [draftChatId, setDraftChatId] = useState<string>();
  const draftChat = isNewThread && !materialized && draftChatId === threadId;
  const mode = savedChat || draftChat ? "chat" : preferred.mode;
  const context = useMemo(() => ({ ...preferred, mode }), [preferred, mode]);
  const loadFailed = !threadMetadata.data && threadMetadata.isError;
  const loading =
    restoring ||
    (!!threadId &&
      !isNewThread &&
      !isMock &&
      (threadMetadata.isLoading || loadFailed));

  const epoch = useRef(0);
  useLayoutEffect(
    () => () => {
      ++epoch.current;
    },
    [threadId, agentName, projectId, userId],
  );
  const writes = useRef(
    new Map<string, { mode: InputMode; done: Promise<void> }>(),
  );
  const [, refreshPending] = useReducer((revision: number) => revision + 1, 0);

  const save = useCallback(
    (id: string, mode: InputMode) => {
      const done = (async () => {
        try {
          await patchThreadMetadata(id, { mode });
          // A GET begun before the PATCH must not restore an older file policy.
          await queryClient.cancelQueries({
            queryKey: ["thread", "metadata", id],
          });
          setThreadMetadataInCaches(queryClient, id, { mode });
        } finally {
          writes.current.delete(id);
          refreshPending();
        }
      })();
      writes.current.set(id, { mode, done });
      refreshPending();
      return done;
    },
    [queryClient],
  );

  const changeMode = useCallback(
    (next: InputMode | undefined, apply: () => void, automatic = false) => {
      if (loading || (threadId && writes.current.has(threadId))) return;
      if (!automatic && next && isNewThread && !materialized && threadId) {
        setDraftChatId(next === "chat" ? threadId : undefined);
      }
      if (
        automatic ||
        !next ||
        !threadId ||
        !materialized ||
        savedChat === (next === "chat")
      ) {
        apply();
        return;
      }
      const selectionEpoch = epoch.current;
      void save(threadId, next)
        .then(() => {
          if (epoch.current === selectionEpoch) apply();
        })
        .catch((error: Error) => {
          if (epoch.current === selectionEpoch) toast.error(error.message);
        });
    },
    [isNewThread, loading, materialized, save, savedChat, threadId],
  );

  const prepareThread = useCallback(
    async (materialize = false) => {
      if (!threadId || isMock) return;
      if (loading) throw new Error("thread-mode-changed");
      const pending = writes.current.get(threadId);
      if (pending) {
        if (pending.mode !== mode) throw new Error("thread-mode-changed");
        await pending.done;
      } else if (isNewThread && (materialize || projectId || mode === "chat")) {
        // Project membership and Chat policy must exist before the first command,
        // file operation or run can materialize the thread under its default policy.
        try {
          const created = await createThread(
            threadId,
            projectId ?? undefined,
            mode === "chat" ? mode : undefined,
            agentName,
          );
          queryClient.setQueryData(
            ["thread", "metadata", threadId, false],
            created,
          );
          void queryClient.invalidateQueries({
            queryKey: INFINITE_THREADS_QUERY_KEY_PREFIX,
          });
        } catch (error) {
          toast.error(
            projectId && projectUnavailable
              ? projectUnavailable
              : String(error),
          );
          throw error;
        }
      } else if (materialized && mode === "chat" && !savedChat) {
        await save(threadId, mode);
      }
    },
    [
      agentName,
      isMock,
      isNewThread,
      loading,
      materialized,
      mode,
      projectId,
      projectUnavailable,
      queryClient,
      save,
      savedChat,
      threadId,
    ],
  );

  return {
    context,
    mode,
    threadMetadata,
    pending: loading || (!!threadId && writes.current.has(threadId)),
    retryMode: loadFailed ? () => void threadMetadata.refetch() : undefined,
    changeMode,
    prepareThread,
  };
}
