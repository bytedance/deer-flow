"use client";

import { ChevronRight, MessagesSquare, Search } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { ThreadChannelIcon } from "@/components/workspace/thread-channel-source";
import { useI18n } from "@/core/i18n/hooks";
import { useInfiniteThreads } from "@/core/threads/hooks";
import {
  channelSourceOfThread,
  pathOfThread,
  titleOfThread,
} from "@/core/threads/utils";
import { formatTimeAgo } from "@/core/utils/datetime";

import { SettingsSection } from "./settings-section";

export function ChatsSettingsPage() {
  const { t } = useI18n();
  const {
    data: infiniteThreads,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
    isLoading,
    error,
    refetch,
  } = useInfiniteThreads();
  const threads = useMemo(
    () => infiniteThreads?.pages.flat() ?? [],
    [infiniteThreads],
  );
  const [search, setSearch] = useState("");
  const isSearching = search.trim().length > 0;

  const filteredThreads = useMemo(() => {
    const query = search.trim().toLowerCase();
    return threads
      .filter((thread) => titleOfThread(thread).toLowerCase().includes(query))
      .sort((a, b) => {
        const aTime = a.updated_at ? Date.parse(a.updated_at) : 0;
        const bTime = b.updated_at ? Date.parse(b.updated_at) : 0;
        return bTime - aTime;
      });
  }, [threads, search]);

  const sentinelRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const element = sentinelRef.current;
    if (!element || !hasNextPage || isSearching) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry?.isIntersecting && hasNextPage && !isFetchingNextPage) {
          void fetchNextPage();
        }
      },
      { rootMargin: "200px 0px 200px 0px" },
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, [fetchNextPage, hasNextPage, isFetchingNextPage, isSearching]);

  const showError = Boolean(error && threads.length === 0);
  const showSkeleton = isLoading && !showError;

  return (
    <SettingsSection
      title={t.settings.sections.chats}
      description={t.chats.description}
    >
      {/* Toolbar */}
      <div className="mb-4 flex items-center gap-2">
        <div className="relative min-w-0 flex-1">
          <Search className="text-muted-foreground pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2" />
          <Input
            type="search"
            className="h-9 pl-9"
            placeholder={t.chats.searchChats}
            aria-label={t.chats.searchChats}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
      </div>

      {/* List */}
      {showError ? (
        <div
          role="alert"
          className="flex flex-col items-center justify-center gap-3 rounded-lg border py-12 text-center"
        >
          <div className="text-destructive text-sm font-medium">
            {t.chats.loadError}: {error?.message}
          </div>
          <Button variant="outline" size="sm" onClick={() => void refetch()}>
            {t.chats.retry}
          </Button>
        </div>
      ) : showSkeleton ? (
        <div className="overflow-hidden rounded-lg border">
          {[0, 1, 2, 3, 4].map((item) => (
            <div
              key={item}
              className="flex min-h-14 items-center gap-3 border-b px-4 last:border-b-0"
            >
              <Skeleton className="size-8 shrink-0 rounded-md" />
              <div className="flex min-w-0 flex-1 flex-col gap-2">
                <Skeleton className="h-4 w-2/3" />
                <Skeleton className="h-3 w-1/4" />
              </div>
              <Skeleton className="size-4 shrink-0 rounded-sm" />
            </div>
          ))}
        </div>
      ) : filteredThreads.length > 0 ? (
        <div className="overflow-hidden rounded-lg border">
          {filteredThreads.map((thread) => {
            const channelSource = channelSourceOfThread(thread);
            return (
              <Link
                key={thread.thread_id}
                href={pathOfThread(thread)}
                className="hover:bg-secondary/50 flex min-h-14 items-center gap-3 border-b px-4 transition-colors last:border-b-0"
              >
                <ThreadChannelIcon source={channelSource} />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium">
                    {titleOfThread(thread)}
                  </div>
                  <div className="text-muted-foreground mt-0.5 flex items-center gap-2 text-xs">
                    <span>
                      {thread.updated_at
                        ? formatTimeAgo(thread.updated_at)
                        : t.pages.untitled}
                    </span>
                    {channelSource ? (
                      <span className="bg-muted rounded px-1.5 py-0.5">
                        {channelSource.label}
                      </span>
                    ) : null}
                  </div>
                </div>
                <ChevronRight
                  className="text-muted-foreground size-4 shrink-0"
                  aria-hidden="true"
                />
              </Link>
            );
          })}
          {hasNextPage && !isSearching ? (
            <div ref={sentinelRef} aria-hidden="true" className="h-px w-full" />
          ) : null}
          {hasNextPage && isSearching ? (
            <div className="flex justify-center border-t p-3">
              <Button
                variant="outline"
                size="sm"
                onClick={() => void fetchNextPage()}
                disabled={isFetchingNextPage}
              >
                {isFetchingNextPage
                  ? t.chats.loadingMore
                  : t.chats.loadMoreToSearch}
              </Button>
            </div>
          ) : null}
        </div>
      ) : (
        <div className="flex flex-col items-center justify-center gap-3 rounded-lg border py-12 text-center">
          <MessagesSquare className="text-muted-foreground/50 size-8" />
          <div>
            <div className="text-sm font-medium">
              {isSearching ? t.chats.noMatches : t.chats.emptyTitle}
            </div>
            {!isSearching ? (
              <div className="text-muted-foreground mt-1 text-xs">
                {t.chats.emptyDescription}
              </div>
            ) : null}
          </div>
        </div>
      )}
    </SettingsSection>
  );
}
