"use client";

import { Archive, MoreHorizontal, RotateCcw, Trash2 } from "lucide-react";
import Link from "next/link";
import { type MouseEvent, useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import { useI18n } from "@/core/i18n/hooks";
import {
  useArchiveThread,
  useDeleteThread,
  useThreads,
} from "@/core/threads/hooks";
import { pathOfThread, titleOfThread } from "@/core/threads/utils";
import { formatTimeAgo } from "@/core/utils/datetime";
import { env } from "@/env";

type ThreadView = "active" | "archived";

export default function ChatsPage() {
  const { t } = useI18n();
  const { data: threads } = useThreads(undefined, { includeArchived: true });
  const { mutate: archiveThread } = useArchiveThread();
  const { mutate: deleteThread } = useDeleteThread();
  const [search, setSearch] = useState("");
  const [threadView, setThreadView] = useState<ThreadView>("active");
  const [selectedThreadIds, setSelectedThreadIds] = useState<Set<string>>(
    () => new Set(),
  );
  const [lastSelectedThreadId, setLastSelectedThreadId] = useState<
    string | null
  >(null);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);

  useEffect(() => {
    document.title = `${t.pages.chats} - ${t.pages.appName}`;
  }, [t.pages.chats, t.pages.appName]);

  const filteredThreads = useMemo(() => {
    return threads?.filter((thread) => {
      const archived = thread.metadata?.archived === true;
      return (
        archived === (threadView === "archived") &&
        titleOfThread(thread).toLowerCase().includes(search.toLowerCase())
      );
    });
  }, [threads, search, threadView]);

  const visibleThreadIds = useMemo(
    () => filteredThreads?.map((thread) => thread.thread_id) ?? [],
    [filteredThreads],
  );
  const visibleThreadIdSet = useMemo(
    () => new Set(visibleThreadIds),
    [visibleThreadIds],
  );
  const selectedCount = selectedThreadIds.size;

  useEffect(() => {
    setSelectedThreadIds((selected) => {
      const visibleSelected = new Set(
        [...selected].filter((threadId) => visibleThreadIdSet.has(threadId)),
      );
      return visibleSelected.size === selected.size
        ? selected
        : visibleSelected;
    });
    setLastSelectedThreadId((threadId) =>
      threadId && visibleThreadIdSet.has(threadId) ? threadId : null,
    );
  }, [visibleThreadIdSet]);

  const handleSelectAll = () => {
    setSelectedThreadIds(new Set(visibleThreadIds));
    setLastSelectedThreadId(visibleThreadIds.at(-1) ?? null);
  };

  const handleClearSelection = () => {
    setSelectedThreadIds(new Set());
    setLastSelectedThreadId(null);
  };

  const handleToggleThreadSelection = (
    threadId: string,
    event: MouseEvent<HTMLInputElement>,
  ) => {
    setSelectedThreadIds((selected) => {
      const nextSelected = new Set(selected);
      if (event.shiftKey && lastSelectedThreadId) {
        const startIndex = visibleThreadIds.indexOf(lastSelectedThreadId);
        const endIndex = visibleThreadIds.indexOf(threadId);
        if (startIndex !== -1 && endIndex !== -1) {
          const [from, to] =
            startIndex < endIndex
              ? [startIndex, endIndex]
              : [endIndex, startIndex];
          visibleThreadIds
            .slice(from, to + 1)
            .forEach((visibleThreadId) => nextSelected.add(visibleThreadId));
          return nextSelected;
        }
      }
      if (nextSelected.has(threadId)) {
        nextSelected.delete(threadId);
      } else {
        nextSelected.add(threadId);
      }
      return nextSelected;
    });
    setLastSelectedThreadId(threadId);
  };

  const handleArchiveSelected = (archived: boolean) => {
    selectedThreadIds.forEach((threadId) => {
      archiveThread({ threadId, archived });
    });
    handleClearSelection();
  };

  const handleDeleteSelected = () => {
    selectedThreadIds.forEach((threadId) => {
      deleteThread({ threadId });
    });
    setDeleteDialogOpen(false);
    handleClearSelection();
  };

  return (
    <WorkspaceContainer>
      <WorkspaceHeader></WorkspaceHeader>
      <WorkspaceBody>
        <div className="flex size-full flex-col">
          <header className="flex shrink-0 items-center justify-center pt-8">
            <div className="flex w-full max-w-(--container-width-md) flex-col gap-3 px-4">
              <Input
                type="search"
                className="h-11 w-full text-base"
                placeholder={t.chats.searchChats}
                autoFocus
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
              <Tabs
                value={threadView}
                onValueChange={(value) => setThreadView(value as ThreadView)}
              >
                <TabsList variant="line">
                  <TabsTrigger value="active">{t.pages.chats}</TabsTrigger>
                  <TabsTrigger value="archived">
                    {t.common.archived}
                  </TabsTrigger>
                </TabsList>
              </Tabs>
              {env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY !== "true" &&
                visibleThreadIds.length > 0 && (
                  <div className="bg-muted/30 flex min-h-9 w-fit max-w-full flex-wrap items-center gap-2 rounded-md border px-2 py-1">
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-7 px-2"
                      onClick={handleSelectAll}
                    >
                      {t.common.selectAll}
                    </Button>
                    {selectedCount > 0 && (
                      <>
                        <span className="text-muted-foreground px-1 text-sm">
                          {t.common.selected} {selectedCount}
                        </span>
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-7 px-2"
                          onClick={() =>
                            handleArchiveSelected(threadView !== "archived")
                          }
                        >
                          {threadView === "archived"
                            ? t.common.restore
                            : t.common.archive}
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          className="text-destructive hover:text-destructive h-7 px-2"
                          onClick={() => setDeleteDialogOpen(true)}
                        >
                          {t.common.delete}
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-7 px-2"
                          onClick={handleClearSelection}
                        >
                          {t.common.cancel}
                        </Button>
                      </>
                    )}
                  </div>
                )}
            </div>
          </header>
          <main className="min-h-0 flex-1">
            <ScrollArea className="size-full py-4">
              <div className="mx-auto flex size-full max-w-(--container-width-md) flex-col gap-1 px-4">
                {filteredThreads?.map((thread) => (
                  <div
                    key={thread.thread_id}
                    data-selected={selectedThreadIds.has(thread.thread_id)}
                    className="group/chat-row hover:bg-muted/40 data-[selected=true]:border-border data-[selected=true]:bg-muted/50 flex items-center gap-3 rounded-md border border-b border-transparent px-3 py-3 transition-colors"
                  >
                    {env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY !== "true" && (
                      <input
                        aria-label={titleOfThread(thread)}
                        type="checkbox"
                        className="size-4 shrink-0 accent-current"
                        checked={selectedThreadIds.has(thread.thread_id)}
                        readOnly
                        onClick={(event) => {
                          event.stopPropagation();
                          handleToggleThreadSelection(thread.thread_id, event);
                        }}
                      />
                    )}
                    <Link
                      className="min-w-0 flex-1"
                      href={pathOfThread(thread)}
                    >
                      <div className="flex min-w-0 flex-col gap-2">
                        <div>{titleOfThread(thread)}</div>
                        {thread.updated_at && (
                          <div className="text-muted-foreground text-sm">
                            {formatTimeAgo(thread.updated_at)}
                          </div>
                        )}
                      </div>
                    </Link>
                    {env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY !== "true" && (
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="size-8 opacity-100 md:opacity-0 md:group-hover/chat-row:opacity-100 md:focus-visible:opacity-100 md:data-[state=open]:opacity-100"
                          >
                            <MoreHorizontal />
                            <span className="sr-only">{t.common.more}</span>
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
                          <DropdownMenuItem
                            onSelect={() =>
                              archiveThread({
                                threadId: thread.thread_id,
                                archived: threadView !== "archived",
                              })
                            }
                          >
                            {threadView === "archived" ? (
                              <>
                                <RotateCcw />
                                <span>{t.common.restore}</span>
                              </>
                            ) : (
                              <>
                                <Archive />
                                <span>{t.common.archive}</span>
                              </>
                            )}
                          </DropdownMenuItem>
                          <DropdownMenuItem
                            variant="destructive"
                            onSelect={() =>
                              deleteThread({ threadId: thread.thread_id })
                            }
                          >
                            <Trash2 />
                            <span>{t.common.delete}</span>
                          </DropdownMenuItem>
                        </DropdownMenuContent>
                      </DropdownMenu>
                    )}
                  </div>
                ))}
              </div>
            </ScrollArea>
          </main>
        </div>
        <Dialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>{t.chats.deleteSelectedTitle}</DialogTitle>
              <DialogDescription>
                {t.chats.deleteSelectedDescription}
              </DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <Button
                variant="outline"
                onClick={() => setDeleteDialogOpen(false)}
              >
                {t.common.cancel}
              </Button>
              <Button variant="destructive" onClick={handleDeleteSelected}>
                {t.common.delete}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}
