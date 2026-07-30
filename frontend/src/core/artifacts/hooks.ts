import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef } from "react";

import { useThread } from "@/components/workspace/messages/context";

import { loadArtifactContent, loadArtifactContentFromToolCall } from "./loader";
import { hasActiveWriteForArtifact } from "./refresh";

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
  const hasActiveWrite = useMemo(
    () => !isWriteFile && hasActiveWriteForArtifact(thread.messages, filepath),
    [filepath, isWriteFile, thread.messages],
  );
  const content = useMemo(() => {
    if (isWriteFile) {
      return loadArtifactContentFromToolCall({ url: filepath, thread });
    }
    return null;
  }, [filepath, isWriteFile, thread]);

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["artifact", filepath, threadId, isMock],
    queryFn: () => {
      return loadArtifactContent({ filepath, threadId, isMock });
    },
    enabled,
    // Poll only the formal file currently shown in the panel. The detail
    // component is unmounted when the panel closes, so this does not poll the
    // whole artifact list or files the user is not viewing. The transient
    // write-file preview is already driven directly by streamed tool arguments.
    refetchInterval:
      enabled && !isWriteFile && (thread.isLoading || hasActiveWrite)
        ? 1000
        : false,
    refetchIntervalInBackground: true,
    staleTime: 0,
    refetchOnWindowFocus: true,
  });

  const wasLoadingRef = useRef(thread.isLoading);
  useEffect(() => {
    const wasLoading = wasLoadingRef.current;
    wasLoadingRef.current = thread.isLoading;
    if (wasLoading && !thread.isLoading && enabled && !isWriteFile) {
      void refetch().catch(() => undefined);
    }
  }, [enabled, isWriteFile, refetch, thread.isLoading]);

  return {
    content: isWriteFile ? content : data?.content,
    url: isWriteFile ? undefined : data?.url,
    isLoading,
    error,
  };
}
