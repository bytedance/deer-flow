"use client";

import {
  ChevronDown,
  ChevronRight,
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
import { useCallback, useEffect, useMemo, useState } from "react";
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
import { getAPIClient } from "@/core/api";
import { getBackendBaseURL } from "@/core/config";
import { useI18n } from "@/core/i18n/hooks";
import {
  exportThreadAsJSON,
  exportThreadAsMarkdown,
} from "@/core/threads/export";
import {
  useDeleteThread,
  useRenameThread,
  useThreads,
} from "@/core/threads/hooks";
import type { AgentThread, AgentThreadState } from "@/core/threads/types";
import { pathOfThread, titleOfThread } from "@/core/threads/utils";
import { env } from "@/env";
import { isIMEComposing } from "@/lib/ime";

function ThreadItem({
  thread,
  isActive,
  pathname,
  handleRenameClick,
  handleShare,
  handleExport,
  handleDelete,
  t,
}: {
  thread: AgentThread;
  isActive: boolean;
  pathname: string;
  handleRenameClick: (threadId: string, currentTitle: string) => void;
  handleShare: (thread: AgentThread) => void;
  handleExport: (thread: AgentThread, format: "markdown" | "json") => void;
  handleDelete: (threadId: string) => void;
  t: any;
}) {
  return (
    <SidebarMenuItem key={thread.thread_id} className="group/side-menu-item">
      <SidebarMenuButton isActive={isActive} asChild>
        <div>
          <Link
            className="text-muted-foreground block w-full whitespace-nowrap group-hover/side-menu-item:overflow-hidden"
            href={pathOfThread(thread)}
          >
            {titleOfThread(thread)}
          </Link>
          {env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY !== "true" && (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <SidebarMenuAction
                  showOnHover
                  className="bg-background/50 hover:bg-background"
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
                    handleRenameClick(thread.thread_id, titleOfThread(thread))
                  }
                >
                  <Pencil className="text-muted-foreground" />
                  <span>{t.common.rename}</span>
                </DropdownMenuItem>
                <DropdownMenuItem onSelect={() => handleShare(thread)}>
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
                      onSelect={() => handleExport(thread, "markdown")}
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
                  onSelect={() => handleDelete(thread.thread_id)}
                >
                  <Trash2 className="text-muted-foreground" />
                  <span>{t.common.delete}</span>
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          )}
        </div>
      </SidebarMenuButton>
    </SidebarMenuItem>
  );
}

export function RecentChatList() {
  const { t } = useI18n();
  const router = useRouter();
  const pathname = usePathname();
  const { thread_id: threadIdFromPath, agent_name: agentNameFromPath } =
    useParams<{
      thread_id: string;
      agent_name?: string;
    }>();
  const { data: threads = [] } = useThreads();
  const { mutate: deleteThread } = useDeleteThread();
  const { mutate: renameThread } = useRenameThread();

  const [threadTags, setThreadTags] = useState<
    Record<string, string | undefined>
  >({});
  const [loadingTags, setLoadingTags] = useState(false);

  const loadThreadTags = useCallback(async () => {
    setLoadingTags(true);
    const tags: Record<string, string | undefined> = {};

    await Promise.all(
      threads.map(async (thread) => {
        try {
          const response = await fetch(
            `${getBackendBaseURL()}/api/global-variables/threads/${thread.thread_id}`,
          );
          if (response.ok) {
            const data = await response.json();
            const novelTagVar = data.variables?.find(
              (v: any) => v.key === "novel_tag",
            );
            tags[thread.thread_id] = novelTagVar?.value;
          }
        } catch {
          // Ignore errors
        }
      }),
    );

    setThreadTags(tags);
    setLoadingTags(false);
  }, [threads]);

  useEffect(() => {
    if (threads.length > 0) {
      void loadThreadTags();
    }
  }, [threads, loadThreadTags]);

  const groupedThreads = useMemo(() => {
    const groups: Record<string, AgentThread[]> = {};

    threads.forEach((thread) => {
      const tag = threadTags[thread.thread_id] || "__undefined__";
      if (!groups[tag]) {
        groups[tag] = [];
      }
      groups[tag].push(thread);
    });

    return groups;
  }, [threads, threadTags]);

  const sortedGroupKeys = useMemo(() => {
    const keys = Object.keys(groupedThreads);
    return keys.sort((a, b) => {
      if (a === "__undefined__") return 1;
      if (b === "__undefined__") return -1;
      return a.localeCompare(b);
    });
  }, [groupedThreads]);

  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set());

  const toggleGroup = useCallback((groupName: string) => {
    setExpandedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(groupName)) {
        next.delete(groupName);
      } else {
        next.add(groupName);
      }
      return next;
    });
  }, []);

  const [renameDialogOpen, setRenameDialogOpen] = useState(false);
  const [renameThreadId, setRenameThreadId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");

  const handleDelete = useCallback(
    (threadId: string) => {
      deleteThread({ threadId });
      if (threadId === threadIdFromPath) {
        const threadIndex = threads.findIndex((t) => t.thread_id === threadId);
        let nextThreadPath = pathOfThread("new", {
          agent_name: agentNameFromPath,
        });
        if (threadIndex > -1) {
          if (threads[threadIndex + 1]) {
            nextThreadPath = pathOfThread(threads[threadIndex + 1]!);
          } else if (threads[threadIndex - 1]) {
            nextThreadPath = pathOfThread(threads[threadIndex - 1]!);
          }
        }
        void router.push(nextThreadPath);
      }
    },
    [agentNameFromPath, deleteThread, router, threadIdFromPath, threads],
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
      const VERCEL_URL = "https://deer-flow-v2.vercel.app";
      const isLocalhost =
        window.location.hostname === "localhost" ||
        window.location.hostname === "127.0.0.1";
      const baseUrl = isLocalhost ? VERCEL_URL : window.location.origin;
      const shareUrl = `${baseUrl}${pathOfThread(thread)}`;
      try {
        await navigator.clipboard.writeText(shareUrl);
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
              {sortedGroupKeys.map((groupKey) => {
                const groupThreads = groupedThreads[groupKey];
                const isExpanded = expandedGroups.has(groupKey);
                const groupName =
                  groupKey === "__undefined__" ? "未分类" : groupKey;

                return (
                  <div key={groupKey} className="mb-2">
                    <button
                      className="text-muted-foreground hover:text-foreground flex w-full items-center gap-1 px-2 py-1 text-xs font-medium"
                      onClick={() => toggleGroup(groupKey)}
                    >
                      {isExpanded ? (
                        <ChevronDown className="size-3" />
                      ) : (
                        <ChevronRight className="size-3" />
                      )}
                      <span>{groupName}</span>
                      <span className="text-muted-foreground/60">
                        ({groupThreads.length})
                      </span>
                    </button>
                    {isExpanded && groupThreads && (
                      <div className="mt-1 ml-2">
                        {groupThreads.map((thread) => {
                          const isActive = pathOfThread(thread) === pathname;
                          return (
                            <ThreadItem
                              key={thread.thread_id}
                              thread={thread}
                              isActive={isActive}
                              pathname={pathname}
                              handleRenameClick={handleRenameClick}
                              handleShare={handleShare}
                              handleExport={handleExport}
                              handleDelete={handleDelete}
                              t={t}
                            />
                          );
                        })}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </SidebarMenu>
        </SidebarGroupContent>
      </SidebarGroup>

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
