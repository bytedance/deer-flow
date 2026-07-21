"use client";

import {
  Download,
  FileJson,
  FileText,
  MoreHorizontal,
  Pencil,
  Share2,
  Trash2,
} from "lucide-react";
import Link from "next/link";
import { useParams, usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import {
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarMenu,
  SidebarMenuAction,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar";
import { resetThreadChatAfterDelete } from "@/components/workspace/chats/use-thread-chat";
import { getAPIClient } from "@/core/api";
import { writeTextToClipboard } from "@/core/clipboard";
import { useI18n } from "@/core/i18n/hooks";
import {
  exportThreadAsJSON,
  exportThreadAsMarkdown,
} from "@/core/threads/export";
import {
  useDeleteThread,
  useInfiniteThreads,
  useRenameThread,
} from "@/core/threads/hooks";
import type { AgentThread, AgentThreadState } from "@/core/threads/types";
import {
  channelSourceOfThread,
  pathOfThread,
  titleOfThread,
} from "@/core/threads/utils";
import { env } from "@/env";
import { isIMEComposing } from "@/lib/ime";

import { ThreadChannelIcon } from "./thread-channel-source";

export function RecentChatList() {
  const { t } = useI18n();
  const router = useRouter();
  const pathname = usePathname();
  const { thread_id: threadIdFromPath, agent_name: agentNameFromPath } =
    useParams<{
      thread_id: string;
      agent_name?: string;
    }>();
  const {
    data: infiniteThreads,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
  } = useInfiniteThreads();
  const threads = useMemo(() => {
    const seen = new Set<string>();
    return (infiniteThreads?.pages.flat() ?? []).filter((thread) => {
      if (seen.has(thread.thread_id)) {
        return false;
      }
      seen.add(thread.thread_id);
      return true;
    });
  }, [infiniteThreads]);

  const sentinelRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const element = sentinelRef.current;
    if (!element || !hasNextPage) {
      return;
    }
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry?.isIntersecting && hasNextPage && !isFetchingNextPage) {
          void fetchNextPage();
        }
      },
      { rootMargin: "120px 0px 120px 0px" },
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, [fetchNextPage, hasNextPage, isFetchingNextPage]);

  const { mutate: deleteThread } = useDeleteThread();
  const { mutate: renameThread } = useRenameThread();

  // Rename dialog state
  const [renameDialogOpen, setRenameDialogOpen] = useState(false);
  const [renameThreadId, setRenameThreadId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");

  const handleDelete = useCallback(
    (thread: AgentThread) => {
      const currentPathname =
        typeof window === "undefined" ? pathname : window.location.pathname;
      const threadPath = pathOfThread(thread);
      const nextThreadPath = pathOfThread("new", {
        agent_name: agentNameFromPath,
      });
      const isNewThreadPath = currentPathname === nextThreadPath;
      const isCurrentThread =
        thread.thread_id === threadIdFromPath ||
        threadPath === currentPathname ||
        (isNewThreadPath && threads[0]?.thread_id === thread.thread_id);

      deleteThread({
        threadId: thread.thread_id,
        onRemoteDeleted: isCurrentThread
          ? () => {
              resetThreadChatAfterDelete({
                deletedThreadId: thread.thread_id,
                nextPath: nextThreadPath,
                force: true,
              });
              void router.replace(nextThreadPath);
            }
          : undefined,
      });
    },
    [
      agentNameFromPath,
      deleteThread,
      pathname,
      router,
      threadIdFromPath,
      threads,
    ],
  );

  const handleRenameClick = useCallback(
    (threadId: string, currentTitle: string) => {
      setRenameThreadId(threadId);
      setRenameValue(currentTitle);
      setRenameDialogOpen(true);
    },
    [],
  );

  const handleRenameSubmit = useCallback(() => {
    if (renameThreadId && renameValue.trim()) {
      renameThread({ threadId: renameThreadId, title: renameValue.trim() });
      setRenameDialogOpen(false);
      setRenameThreadId(null);
      setRenameValue("");
    }
  }, [renameThread, renameThreadId, renameValue]);

  const handleShare = useCallback(
    async (thread: AgentThread) => {
      // Always use Vercel URL for sharing so others can access
      const VERCEL_URL = "https://deer-flow-v2.vercel.app";
      const isLocalhost =
        window.location.hostname === "localhost" ||
        window.location.hostname === "127.0.0.1";
      // On localhost: use Vercel URL; On production: use current origin
      const baseUrl = isLocalhost ? VERCEL_URL : window.location.origin;
      const shareUrl = `${baseUrl}${pathOfThread(thread)}`;
      try {
        const didCopy = await writeTextToClipboard(shareUrl);
        if (!didCopy) {
          toast.error(t.clipboard.failedToCopyToClipboard);
          return;
        }

        toast.success(t.clipboard.linkCopied);
      } catch {
        toast.error(t.clipboard.failedToCopyToClipboard);
      }
    },
    [t],
  );

  const handleExport = useCallback(
    async (thread: AgentThread, format: "markdown" | "json") => {
      try {
        const apiClient = getAPIClient();
        const state = await apiClient.threads.getState<AgentThreadState>(
          thread.thread_id,
        );
        const messages = state.values?.messages ?? [];
        if (messages.length === 0) {
          toast.error(t.conversation.noMessages);
          return;
        }
        if (format === "markdown") {
          exportThreadAsMarkdown(thread, messages);
        } else {
          exportThreadAsJSON(thread, messages);
        }
        toast.success(t.common.exportSuccess);
      } catch {
        toast.error("Failed to export conversation");
      }
    },
    [t],
  );

  if (threads.length === 0) {
    return null;
  }
  return (
    <>
      <SidebarGroup>
        <SidebarGroupLabel>
          {env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY !== "true"
            ? t.sidebar.recentChats
            : t.sidebar.demoChats}
        </SidebarGroupLabel>
        <SidebarGroupContent className="group-data-[collapsible=icon]:pointer-events-none group-data-[collapsible=icon]:-mt-8 group-data-[collapsible=icon]:opacity-0">
          <SidebarMenu>
            <div className="flex w-full flex-col gap-1">
              {threads.map((thread) => {
                const isActive = pathOfThread(thread) === pathname;
                const channelSource = channelSourceOfThread(thread);
                return (
                  <SidebarMenuItem
                    key={thread.thread_id}
                    className="group/side-menu-item"
                  >
                    <SidebarMenuButton isActive={isActive} asChild>
                      <Link
                        className="text-muted-foreground min-w-0 whitespace-nowrap group-hover/side-menu-item:overflow-hidden"
                        href={pathOfThread(thread)}
                      >
                        <ThreadChannelIcon source={channelSource} />
                        <span className="min-w-0 truncate">
                          {titleOfThread(thread)}
                        </span>
                        {channelSource && (
                          <span
                            className="bg-muted text-muted-foreground ml-auto inline-flex h-5 max-w-14 shrink-0 items-center rounded-md px-1.5 text-[10px] font-medium"
                            title={`${channelSource.label} channel`}
                          >
                            <span className="truncate">
                              {channelSource.label}
                            </span>
                          </span>
                        )}
                      </Link>
                    </SidebarMenuButton>
                    {env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY !== "true" && (
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <SidebarMenuAction
                            showOnHover
                            className="bg-background/50 hover:bg-background after:left-0!"
                          >
                            <MoreHorizontal />
                            <span className="sr-only">{t.common.more}</span>
                          </SidebarMenuAction>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent
                          className="w-48 rounded-lg"
                          side={"right"}
                          align={"start"}
                        >
                          <DropdownMenuItem
                            onSelect={() =>
                              handleRenameClick(
                                thread.thread_id,
                                titleOfThread(thread),
                              )
                            }
                          >
                            <Pencil className="text-muted-foreground" />
                            <span>{t.common.rename}</span>
                          </DropdownMenuItem>
                          <DropdownMenuItem
                            onSelect={() => handleShare(thread)}
                          >
                            <Share2 className="text-muted-foreground" />
                            <span>{t.common.share}</span>
                          </DropdownMenuItem>
                          <DropdownMenuSub>
                            <DropdownMenuSubTrigger>
                              <Download className="text-muted-foreground" />
                              <span>{t.common.export}</span>
                            </DropdownMenuSubTrigger>
                            <DropdownMenuSubContent>
                              <DropdownMenuItem
                                onSelect={() =>
                                  handleExport(thread, "markdown")
                                }
                              >
                                <FileText className="text-muted-foreground" />
                                <span>{t.common.exportAsMarkdown}</span>
                              </DropdownMenuItem>
                              <DropdownMenuItem
                                onSelect={() => handleExport(thread, "json")}
                              >
                                <FileJson className="text-muted-foreground" />
                                <span>{t.common.exportAsJSON}</span>
                              </DropdownMenuItem>
                            </DropdownMenuSubContent>
                          </DropdownMenuSub>
                          <DropdownMenuSeparator />
                          <DropdownMenuItem
                            onSelect={() => handleDelete(thread)}
                          >
                            <Trash2 className="text-muted-foreground" />
                            <span>{t.common.delete}</span>
                          </DropdownMenuItem>
                        </DropdownMenuContent>
                      </DropdownMenu>
                    )}
                  </SidebarMenuItem>
                );
              })}
              {hasNextPage && (
                <>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="mx-2 my-1 w-[calc(100%-1rem)] justify-center text-xs"
                    onClick={() => void fetchNextPage()}
                    disabled={isFetchingNextPage}
                    data-testid="recent-chat-list-load-more"
                  >
                    {isFetchingNextPage
                      ? t.chats.loadingMore
                      : t.chats.loadOlderChats}
                  </Button>
                  <div
                    ref={sentinelRef}
                    aria-hidden="true"
                    className="h-px w-full"
                    data-testid="recent-chat-list-sentinel"
                  />
                </>
              )}
            </div>
          </SidebarMenu>
        </SidebarGroupContent>
      </SidebarGroup>

      {/* Rename Dialog */}
      <Dialog open={renameDialogOpen} onOpenChange={setRenameDialogOpen}>
        <DialogContent className="sm:max-w-[425px]">
          <DialogHeader>
            <DialogTitle>{t.common.rename}</DialogTitle>
          </DialogHeader>
          <div className="py-4">
            <Input
              value={renameValue}
              onChange={(e) => setRenameValue(e.target.value)}
              placeholder={t.common.rename}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !isIMEComposing(e)) {
                  e.preventDefault();
                  handleRenameSubmit();
                }
              }}
            />
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setRenameDialogOpen(false)}
            >
              {t.common.cancel}
            </Button>
            <Button onClick={handleRenameSubmit}>{t.common.save}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
