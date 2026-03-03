import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";

import { useThread } from "@/components/workspace/messages/context";

import {
  type McpDataPayload,
  loadArtifactContent,
  loadArtifactContentFromToolCall,
  loadMcpDataFromToolCall,
} from "./loader";

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
  const { thread } = useThread();
  const content = useMemo(() => {
    if (isWriteFile) {
      return loadArtifactContentFromToolCall({ url: filepath, thread });
    }
    return null;
  }, [filepath, isWriteFile, thread]);
  const { data, isLoading, error } = useQuery({
    queryKey: ["artifact", filepath, threadId],
    queryFn: () => {
      return loadArtifactContent({ filepath, threadId });
    },
    enabled,
    // Cache artifact content for 5 minutes to avoid repeated fetches (especially for .skill ZIP extraction)
    staleTime: 5 * 60 * 1000,
  });
  return { content: isWriteFile ? content : data, isLoading, error };
}

export function useMcpDataContent({
  filepath,
}: {
  filepath: string;
}): McpDataPayload | undefined {
  const { thread } = useThread();
  return useMemo(() => {
    if (!filepath.startsWith("mcp-data:")) return undefined;
    return loadMcpDataFromToolCall({ url: filepath, thread });
  }, [filepath, thread]);
}
