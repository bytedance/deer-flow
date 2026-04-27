"use client";

import {
  Download,
  FileJson,
  FileText,
  GitBranch,
  MoreHorizontal,
  Pencil,
  Share2,
  Trash2,
} from "lucide-react";
import Link from "next/link";
import { useParams, usePathname, useRouter } from "next/navigation";
import { useCallback, useState } from "react";
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
import {
  isBranchThreadMetadata,
  pathOfThread,
  titleOfThread,
} from "@/core/threads/utils";
import { env } from "@/env";
import { isIMEComposing } from "@/lib/ime";

type ThreadTreeNode = {
  thread: AgentThread;
  children: ThreadTreeNode[];
  latestUpdatedAt: number;
};

function parseThreadUpdatedAt(value: string | undefined) {
  if (!value) {
    return 0;
  }

  const numeric = Number(value);
  if (Number.isFinite(numeric)) {
    return numeric;
  }

  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function finalizeThreadNode(node: ThreadTreeNode) {
  for (const child of node.children) {
    finalizeThreadNode(child);
    node.latestUpdatedAt = Math.max(
      node.latestUpdatedAt,
      child.latestUpdatedAt,
    );
  }

  node.children.sort(
    (left, right) => right.latestUpdatedAt - left.latestUpdatedAt,
  );
}

function buildThreadTree(threads: AgentThread[]) {
  const nodes = new Map<string, ThreadTreeNode>();
  for (const thread of threads) {
    nodes.set(thread.thread_id, {
      thread,
      children: [],
      latestUpdatedAt: parseThreadUpdatedAt(thread.updated_at),
    });
  }

  const roots: ThreadTreeNode[] = [];
  for (const thread of threads) {
    const node = nodes.get(thread.thread_id);
    if (!node) {
      continue;
    }

    const parentThreadId =
      typeof thread.metadata?.parent_thread_id === "string"
        ? thread.metadata.parent_thread_id
        : undefined;

    if (
      isBranchThreadMetadata(thread.metadata) &&
      parentThreadId &&
      parentThreadId !== thread.thread_id
    ) {
      const parentNode = nodes.get(parentThreadId);
      if (parentNode) {
        parentNode.children.push(node);
        continue;
      }
    }

    roots.push(node);
  }

  for (const root of roots) {
    finalizeThreadNode(root);
  }
  roots.sort((left, right) => right.latestUpdatedAt - left.latestUpdatedAt);

  return roots;
}

function flattenThreadTree(nodes: ThreadTreeNode[]) {
  const ordered: AgentThread[] = [];

  const visit = (items: ThreadTreeNode[]) => {
    for (const item of items) {
      ordered.push(item.thread);
      visit(item.children);
    }
  };

  visit(nodes);
  return ordered;
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
  const threadTree = buildThreadTree(threads);
  const orderedThreads = flattenThreadTree(threadTree);
  const { mutate: deleteThread } = useDeleteThread();
  const { mutate: renameThread } = useRenameThread();

  // Rename dialog state
  const [renameDialogOpen, setRenameDialogOpen] = useState(false);
  const [renameThreadId, setRenameThreadId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");

  const handleDelete = useCallback(
    (threadId: string) => {
      deleteThread({ threadId });
      if (threadId === threadIdFromPath) {
        const threadIndex = orderedThreads.findIndex(
          (t) => t.thread_id === threadId,
        );
        let nextThreadPath = pathOfThread("new", {
          agent_name: agentNameFromPath,
        });
        if (threadIndex > -1) {
          if (orderedThreads[threadIndex + 1]) {
            nextThreadPath = pathOfThread(orderedThreads[threadIndex + 1]!);
          } else if (orderedThreads[threadIndex - 1]) {
            nextThreadPath = pathOfThread(orderedThreads[threadIndex - 1]!);
          }
        }
        void router.push(nextThreadPath);
      }
    },
    [agentNameFromPath, deleteThread, orderedThreads, router, threadIdFromPath],
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

  const renderThreadNode = (
    node: ThreadTreeNode,
    depth = 0,
  ): React.ReactNode => {
    const thread = node.thread;
    const isBranch = isBranchThreadMetadata(thread.metadata);
    const threadPath = pathOfThread(thread);
    const isActive = threadPath === pathname;

    return (
      <div key={thread.thread_id} className="flex flex-col gap-1">
        <SidebarMenuItem
          className="group/side-menu-item"
          style={depth > 0 ? { marginLeft: `${depth * 14}px` } : undefined}
        >
          <SidebarMenuButton isActive={isActive} asChild>
            <div>
              <Link
                className="text-muted-foreground block w-full whitespace-nowrap group-hover/side-menu-item:overflow-hidden"
                href={threadPath}
              >
                <span className="inline-flex items-center gap-1">
                  {isBranch ? <GitBranch className="h-3 w-3 shrink-0" /> : null}
                  <span>{titleOfThread(thread)}</span>
                </span>
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
                        handleRenameClick(
                          thread.thread_id,
                          titleOfThread(thread),
                        )
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
        {node.children.map((child) => renderThreadNode(child, depth + 1))}
      </div>
    );
  };

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
              {threadTree.map((node) => renderThreadNode(node))}
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
