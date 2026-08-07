"use client";

import { usePathname } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { Shell, ShellHeader, WorkspaceIndexList } from "@/components/component";
import { ChatListRow } from "@/components/workspace/chats/chat-list-row";
import { useI18n } from "@/core/i18n/hooks";
import { useInfiniteThreads } from "@/core/threads/hooks";
import { buildThreadListModel } from "@/core/threads/thread-list-model";
import { pathOfThread, titleOfThread } from "@/core/threads/utils";

export default function ChatsPage() {
  const { t } = useI18n();
  const pathname = usePathname();
  const {
    data: infiniteThreads,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
  } = useInfiniteThreads();
  const threadListModel = useMemo(
    () => buildThreadListModel(infiniteThreads?.pages ?? []),
    [infiniteThreads?.pages],
  );
  const { threads } = threadListModel;
  const [search, setSearch] = useState("");
  const isSearching = search.trim().length > 0;

  useEffect(() => {
    document.title = `${t.chats.pageTitle} - ${t.pages.appName}`;
  }, [t.chats.pageTitle, t.pages.appName]);

  const filteredThreads = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return threads;
    return threads.filter((thread) =>
      titleOfThread(thread).toLowerCase().includes(q),
    );
  }, [threads, search]);

  const countLabel = useMemo(() => {
    if (isSearching && filteredThreads.length !== threads.length) {
      return t.chats.countFiltered(filteredThreads.length, threads.length);
    }
    if (hasNextPage && !isSearching) {
      return `${threads.length}+`;
    }
    if (!isSearching) {
      return t.chats.countTotal(filteredThreads.length);
    }
    return String(filteredThreads.length);
  }, [
    filteredThreads.length,
    hasNextPage,
    isSearching,
    t.chats,
    threads.length,
  ]);

  return (
    <Shell
      fillBody={filteredThreads.length === 0}
      header={
        <ShellHeader
          title={t.chats.pageTitle}
          description={t.chats.pageDescription}
        />
      }
    >
      <WorkspaceIndexList
        title={t.chats.listTitle}
        countLabel={countLabel}
        search={{
          value: search,
          onChange: setSearch,
          placeholder: t.chats.searchChats,
          autoFocus: true,
        }}
        pagination={{
          hasNextPage: Boolean(hasNextPage),
          isFetchingNextPage,
          onLoadMore: fetchNextPage,
          loadMoreLabel: t.chats.loadOlderChats,
          loadMoreSearchLabel: t.chats.loadMoreToSearch,
          loadingLabel: t.chats.loadingMore,
          loadMoreTestId: "chats-page-load-more",
          sentinelTestId: "chats-page-sentinel",
          listLength: threads.length,
        }}
        isEmpty={threads.length === 0}
        empty={t.chats.emptyList}
        isSearchEmpty={isSearching && filteredThreads.length === 0}
        searchEmpty={t.chats.searchEmpty}
        emptyClassName="py-16"
      >
        {filteredThreads.map((thread) => (
          <ChatListRow
            key={thread.thread_id}
            thread={thread}
            selected={pathname === pathOfThread(thread)}
          />
        ))}
      </WorkspaceIndexList>
    </Shell>
  );
}
