"use client";

import type { BaseStream } from "@langchain/langgraph-sdk/react";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { SidebarProvider } from "@/components/ui/sidebar";
import { ArtifactsProvider } from "@/components/workspace/artifacts";
import { MessageList } from "@/components/workspace/messages";
import { getBackendBaseURL } from "@/core/config";
import { SubtasksProvider } from "@/core/tasks/context";
import type { AgentThreadState, ThreadShareResponse } from "@/core/threads";

export default function SharePage() {
  const { share_id: shareId } = useParams<{ share_id: string }>();
  const [share, setShare] = useState<ThreadShareResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function loadShare() {
      try {
        const response = await fetch(
          `${getBackendBaseURL()}/api/shares/${encodeURIComponent(shareId)}`,
        );
        if (!response.ok) {
          throw new Error("Share not found");
        }
        const data = (await response.json()) as ThreadShareResponse;
        if (!cancelled) {
          setShare(data);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load share");
        }
      }
    }

    void loadShare();
    return () => {
      cancelled = true;
    };
  }, [shareId]);

  const thread = useMemo(
    () =>
      ({
        messages: share?.messages ?? [],
        values: {
          title: share?.title ?? "",
          messages: share?.messages ?? [],
          artifacts: [],
        },
        isLoading: false,
        isThreadLoading: share === null && error === null,
        getMessagesMetadata: () => [],
      }) as unknown as BaseStream<AgentThreadState>,
    [error, share],
  );

  return (
    <SubtasksProvider>
      <SidebarProvider defaultOpen={false}>
        <ArtifactsProvider>
          <main className="bg-background flex min-h-screen flex-col">
            <header className="bg-background/80 sticky top-0 z-20 border-b px-4 py-3 backdrop-blur">
              <div className="mx-auto flex w-full max-w-(--container-width-md) items-center justify-between gap-3">
                <div className="min-w-0">
                  <div className="text-primary font-serif text-lg">
                    DeerFlow
                  </div>
                  {share?.title && (
                    <h1 className="truncate text-sm font-medium">
                      {share.title}
                    </h1>
                  )}
                </div>
              </div>
            </header>
            {error ? (
              <div className="text-muted-foreground flex flex-1 items-center justify-center px-4 text-sm">
                {error}
              </div>
            ) : (
              <div className="min-h-0 flex-1">
                <MessageList
                  className="min-h-screen"
                  threadId={shareId}
                  thread={thread}
                  hasMoreHistory={false}
                  enableSharing={false}
                />
              </div>
            )}
          </main>
        </ArtifactsProvider>
      </SidebarProvider>
    </SubtasksProvider>
  );
}
