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
  const [fullFilepath, setFullFilepath] = useState<string | null>(null);
  const fullContentRequested = fullFilepath === filepath;
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
    setFullFilepath(filepath);
  }, [filepath]);

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
