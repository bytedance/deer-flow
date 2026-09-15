import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useThread } from "@/components/workspace/messages/context";

import { loadArtifactContent, loadArtifactContentFromToolCall } from "./loader";

export function useArtifactContent({
  filepath,
  threadId,
  enabled,
}: {
  filepath: string;
  threadId: string;
  enabled?: boolean;
}) {
  const isWriteFile = useMemo(() => {
    return filepath.startsWith("write-file:");
  }, [filepath]);
  const { thread, isMock } = useThread();
  const [fullContentSelection, setFullContentSelection] = useState<{
    filepath: string;
    threadId: string;
  } | null>(null);
  const fullContentRequested =
    fullContentSelection?.filepath === filepath &&
    fullContentSelection.threadId === threadId;
  const content = useMemo(() => {
    if (isWriteFile) {
      return loadArtifactContentFromToolCall({ url: filepath, thread });
    }
    return null;
  }, [filepath, isWriteFile, thread]);

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["artifact", filepath, threadId, isMock, fullContentRequested],
    queryFn: () => {
      return loadArtifactContent({
        filepath,
        threadId,
        isMock,
        full: fullContentRequested,
      });
    },
    enabled,
    staleTime: 0,
    refetchOnWindowFocus: true,
  });

  // Refetch once when the run settles so edits made during the run are
  // visible without a manual reload.
  const wasLoadingRef = useRef(thread.isLoading);
  useEffect(() => {
    const wasLoading = wasLoadingRef.current;
    wasLoadingRef.current = thread.isLoading;
    if (wasLoading && !thread.isLoading && enabled && !isWriteFile) {
      void refetch().catch(() => undefined);
    }
  }, [enabled, isWriteFile, refetch, thread.isLoading]);

  const loadFullContent = useCallback(() => {
    setFullContentSelection({ filepath, threadId });
  }, [filepath, threadId]);

  return {
    content: isWriteFile ? content : data?.content,
    url: isWriteFile ? undefined : data?.url,
    sha256: isWriteFile ? undefined : data?.sha256,
    truncated: isWriteFile ? false : (data?.truncated ?? false),
    previewBytes: isWriteFile ? undefined : data?.previewBytes,
    totalBytes: isWriteFile ? undefined : data?.totalBytes,
    fullContentRequested,
    loadFullContent,
    isLoading,
    error,
  };
}

/**
 * Artifact content for the standalone viewer route.
 *
 * Deliberately separate from ``useArtifactContent``: that hook reads the live
 * thread stream through ``useThread`` so it can refetch when a run settles,
 * and the viewer window has no thread context to read. The query key matches
 * so both share the cache when they happen to run in the same document.
 */
export function useStandaloneArtifactContent({
  filepath,
  threadId,
  isMock = false,
}: {
  filepath: string;
  threadId: string;
  isMock?: boolean;
}) {
  const [fullContentSelection, setFullContentSelection] = useState<{
    filepath: string;
    threadId: string;
  } | null>(null);
  const fullContentRequested =
    fullContentSelection?.filepath === filepath &&
    fullContentSelection.threadId === threadId;

  const { data, isLoading, error } = useQuery({
    queryKey: ["artifact", filepath, threadId, isMock, fullContentRequested],
    queryFn: () =>
      loadArtifactContent({
        filepath,
        threadId,
        isMock,
        full: fullContentRequested,
      }),
    staleTime: 0,
    refetchOnWindowFocus: true,
  });

  const loadFullContent = useCallback(() => {
    setFullContentSelection({ filepath, threadId });
  }, [filepath, threadId]);

  return {
    content: data?.content,
    url: data?.url,
    truncated: data?.truncated ?? false,
    previewBytes: data?.previewBytes,
    totalBytes: data?.totalBytes,
    fullContentRequested,
    loadFullContent,
    isLoading,
    error,
  };
}
