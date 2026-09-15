"use client";

import Link from "next/link";

import { Button } from "@/components/ui/button";
import { VirtualThreadList } from "@/components/workspace/thread-list-virtualizer";
import { useI18n } from "@/core/i18n/hooks";
import { type ProjectThreadsQueryResult } from "@/core/projects";
import { pathOfThread } from "@/core/threads/utils";
import { formatTimeAgo } from "@/core/utils/datetime";
import { cn } from "@/lib/utils";

export function ProjectThreadsSection({
  query,
}: {
  query: ProjectThreadsQueryResult;
}) {
  const { t } = useI18n();
  const threads = query.data?.pages.flatMap((page) => page) ?? [];
  return (
    <section className="flex flex-col gap-2">
      <h2 className="text-muted-foreground text-sm font-medium">
        {t.projects.threads}
      </h2>
      <div className="rounded-lg border">
        {query.isError ? (
          <div className="text-muted-foreground p-4 text-sm">
            {t.projects.threadsLoadFailed}
          </div>
        ) : threads.length === 0 && !query.isLoading ? (
          <div className="text-muted-foreground p-4 text-sm">
            {t.projects.empty}
          </div>
        ) : (
          // The page scrolls inside its own ScrollArea; the list windows rows
          // against that viewport so paging through a long-lived project never
          // grows unbounded DOM (same windowing the sidebar and
          // /workspace/chats use).
          <VirtualThreadList
            estimateSize={56}
            items={threads}
            scrollParentSelector='[data-slot="scroll-area-viewport"]'
            renderItem={(thread, index) => (
              <Link
                key={thread.thread_id}
                href={pathOfThread({
                  thread_id: thread.thread_id,
                  metadata: thread.metadata,
                })}
              >
                <div
                  className={cn(
                    "hover:bg-muted/50 flex min-w-0 items-center gap-2 p-4 transition-colors",
                    index !== threads.length - 1 && "border-b",
                  )}
                >
                  <div className="min-w-0 flex-1 truncate">
                    {thread.display_name?.trim()
                      ? thread.display_name
                      : t.projects.untitled}
                  </div>
                  {thread.updated_at && (
                    <div className="text-muted-foreground shrink-0 text-sm">
                      {formatTimeAgo(thread.updated_at)}
                    </div>
                  )}
                </div>
              </Link>
            )}
          />
        )}
      </div>
      {query.hasNextPage && (
        <Button
          variant="ghost"
          size="sm"
          className="justify-center text-xs"
          onClick={() => void query.fetchNextPage()}
          disabled={query.isFetchingNextPage}
          data-testid="project-threads-load-more"
        >
          {query.isFetchingNextPage
            ? t.chats.loadingMore
            : t.chats.loadOlderChats}
        </Button>
      )}
    </section>
  );
}
