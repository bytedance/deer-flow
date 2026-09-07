"use client";

import {
  Archive,
  Download,
  FileJson,
  FileText,
  MoreHorizontal,
  Pencil,
  Pin,
  PinOff,
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
import { useProjects } from "@/core/projects";
import { useLocalSettings } from "@/core/settings";
import { isStaticWebsiteOnly } from "@/core/static-mode";
import { exportThread, type ThreadExportFormat } from "@/core/threads/export";
import {
  useDeleteThread,
  useInfiniteThreads,
  useMoveThreadToProject,
  usePinThread,
  useRenameThread,
} from "@/core/threads/hooks";
import {
  flattenThreadBranches,
  type ThreadBranchEntry,
} from "@/core/threads/thread-branch-tree";
import { buildThreadListModel } from "@/core/threads/thread-list-model";
import type { AgentThread, AgentThreadState } from "@/core/threads/types";
import {
  channelSourceOfThread,
  isThreadPinned,
  pathOfThread,
  projectIdOfThread,
  titleOfThread,
} from "@/core/threads/utils";
import { env } from "@/env";
import { isIMEComposing } from "@/lib/ime";

import { MoveToProjectMenu, NewProjectDialog } from "./move-to-project-menu";
import { ThreadChannelIcon } from "./thread-channel-source";
import { VirtualThreadList } from "./thread-list-virtualizer";
import { useThreadArchiveAction } from "./use-thread-archive-action";

/**
 * A single thread row in the sidebar: link + hover action menu (pin, rename,
 * share, export, delete) + rename dialog. Shared by the flat recent-chat list
 * and the grouped-by-project rendering in `ProjectsSection`.
 */
export function ThreadSidebarItem({
  thread,
  isActive,
  branchEntry,
  recentThreadId,
}: {
  thread: AgentThread;
  isActive: boolean;
  branchEntry?: ThreadBranchEntry | undefined;
  recentThreadId?: string | undefined;
}) {
  const { t } = useI18n();
  const router = useRouter();
  const pathname = usePathname();
  const { thread_id: threadIdFromPath, agent_name: agentNameFromPath } =
    useParams<{
      thread_id: string;
      agent_name?: string;
    }>();
  const { mutate: deleteThread } = useDeleteThread();
  const { mutate: renameThread } = useRenameThread();
  const { mutate: updatePinnedThread } = usePinThread();
  // The move mutation is owned here (not inside `MoveToProjectMenu`) because
  // selecting a project closes the dropdown and unmounts the menu — a
  // per-mutate `onError` registered there would be dropped before a failed
  // request settles, failing silently. This row persists, so a hook-level
  // `onError` always fires. Same ownership-hoisting precedent as the
  // `NewProjectDialog` below.
  const { mutate: moveThreadToProject } = useMoveThreadToProject({
    onError: (error) => {
      toast.error(
        error instanceof Error && error.message
          ? error.message
          : t.projects.moveFailed,
      );
    },
  });

  const handleMoveProject = useCallback(
    (projectId: string | null) => {
      moveThreadToProject({ threadId: thread.thread_id, projectId });
    },
    [moveThreadToProject, thread.thread_id],
  );
  const archiveAction = useThreadArchiveAction();

  const [renameDialogOpen, setRenameDialogOpen] = useState(false);
  const [renameValue, setRenameValue] = useState("");
  const [newProjectDialogOpen, setNewProjectDialogOpen] = useState(false);

  const handleDelete = useCallback(() => {
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
      (isNewThreadPath && recentThreadId === thread.thread_id);

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
  }, [
    agentNameFromPath,
    deleteThread,
    pathname,
    recentThreadId,
    router,
    thread,
    threadIdFromPath,
  ]);

  const handleRenameSubmit = useCallback(() => {
    if (renameValue.trim()) {
      renameThread(
        { threadId: thread.thread_id, title: renameValue.trim() },
        {
          onSuccess: () => {
            setRenameDialogOpen(false);
            setRenameValue("");
          },
          onError: (error) => {
            toast.error(
              error instanceof Error && error.message
                ? error.message
                : t.common.renameFailed,
            );
          },
        },
      );
    }
  }, [renameThread, thread.thread_id, renameValue, t.common.renameFailed]);

  const handleTogglePin = useCallback(() => {
    updatePinnedThread(
      {
        threadId: thread.thread_id,
        pinned: !isThreadPinned(thread),
      },
      {
        onError: (err) => {
          toast.error(
            err instanceof Error ? err.message : t.chats.pinChatFailed,
          );
        },
      },
    );
  }, [t.chats.pinChatFailed, thread, updatePinnedThread]);

  const handleShare = useCallback(async () => {
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
  }, [t, thread]);

  const handleExport = useCallback(
    async (format: ThreadExportFormat) => {
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
        exportThread(thread, messages, format);
        toast.success(t.common.exportSuccess);
      } catch {
        toast.error(t.common.exportFailed);
      }
    },
    [t, thread],
  );

  const channelSource = channelSourceOfThread(thread);
  const pinned = isThreadPinned(thread);
  const parentTitle = branchEntry?.parentThread
    ? titleOfThread(branchEntry.parentThread)
    : null;
  const title = titleOfThread(thread);
  const branchLabel = parentTitle
    ? t.chats.branchLabel(title, parentTitle)
    : undefined;

  return (
    <SidebarMenuItem className="group/side-menu-item">
      <SidebarMenuButton isActive={isActive} asChild>
        <Link
          aria-label={branchLabel}
          className="text-muted-foreground min-w-0 whitespace-nowrap group-hover/side-menu-item:overflow-hidden"
          data-branch-depth={
            branchEntry && branchEntry.depth > 0 ? branchEntry.depth : undefined
          }
          data-branch-parent-id={branchEntry?.parentThread?.thread_id}
          href={pathOfThread(thread)}
          title={branchLabel}
        >
          {branchEntry && branchEntry.depth > 0 && (
            <span
              aria-hidden="true"
              className="text-muted-foreground/70 shrink-0 font-mono text-[10px] leading-none"
              data-testid="thread-branch-stem"
              style={{
                marginLeft: `${Math.min(branchEntry.depth - 1, 1) * 8}px`,
              }}
            >
              {branchEntry.isLastSibling ? "└─" : "├─"}
            </span>
          )}
          <ThreadChannelIcon source={channelSource} />
          {pinned && (
            <Pin
              aria-hidden="true"
              className="text-muted-foreground size-3.5 shrink-0"
            />
          )}
          <span className="min-w-0 truncate">{title}</span>
          {channelSource && (
            <span
              className="bg-muted text-muted-foreground ml-auto inline-flex h-5 max-w-14 shrink-0 items-center rounded-md px-1.5 text-[10px] font-medium"
              title={`${channelSource.label} channel`}
            >
              <span className="truncate">{channelSource.label}</span>
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
            <DropdownMenuItem onSelect={handleTogglePin}>
              {pinned ? (
                <PinOff className="text-muted-foreground" />
              ) : (
                <Pin className="text-muted-foreground" />
              )}
              <span>{pinned ? t.chats.unpinChat : t.chats.pinChat}</span>
            </DropdownMenuItem>
            <DropdownMenuItem
              onSelect={() => {
                setRenameValue(titleOfThread(thread));
                setRenameDialogOpen(true);
              }}
            >
              <Pencil className="text-muted-foreground" />
              <span>{t.common.rename}</span>
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={() => void handleShare()}>
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
                  onSelect={() => void handleExport("markdown")}
                >
                  <FileText className="text-muted-foreground" />
                  <span>{t.common.exportAsMarkdown}</span>
                </DropdownMenuItem>
                <DropdownMenuItem onSelect={() => void handleExport("json")}>
                  <FileJson className="text-muted-foreground" />
                  <span>{t.common.exportAsJSON}</span>
                </DropdownMenuItem>
              </DropdownMenuSubContent>
            </DropdownMenuSub>
            <DropdownMenuItem
              disabled={archiveAction.isPending}
              onSelect={() => archiveAction.setArchived(thread.thread_id, true)}
            >
              <Archive className="text-muted-foreground" />
              <span>{t.chats.archiveChat}</span>
            </DropdownMenuItem>
            <MoveToProjectMenu
              thread={thread}
              onNewProject={() => setNewProjectDialogOpen(true)}
              onMoveProject={handleMoveProject}
            />
            <DropdownMenuSeparator />
            <DropdownMenuItem onSelect={handleDelete}>
              <Trash2 className="text-muted-foreground" />
              <span>{t.common.delete}</span>
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      )}

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
      {/* New Project Dialog (mounted outside the DropdownMenu so it survives
          the menu closing when "New project…" is selected) */}
      <NewProjectDialog
        thread={thread}
        open={newProjectDialogOpen}
        onOpenChange={setNewProjectDialogOpen}
      />
    </SidebarMenuItem>
  );
}

export function RecentChatList() {
  const { t } = useI18n();
  const pathname = usePathname();
  const { thread_id: threadIdFromPath } = useParams<{
    thread_id: string;
    agent_name?: string;
  }>();
  const [settings] = useLocalSettings();
  const groupByProject = settings.projectsDisplayMode === "grouped";
  // Static-demo mode never renders project groups (ProjectsSection is hidden
  // and project queries stay off), so a persisted "grouped" preference must
  // behave as flat — otherwise assigned threads would vanish from this list.
  const grouped = groupByProject && !isStaticWebsiteOnly();
  const {
    data: infiniteThreads,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
  } = useInfiniteThreads({
    archived:
      env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true" ? undefined : false,
  });
  // Project discovery doubles as the exclusion oracle for grouped mode: an
  // assigned thread may leave this flat list ONLY when its project group can
  // actually render in `ProjectsSection`. Any query error (or not-yet-loaded
  // data) yields `null` → exclude nothing (fail-visible), and a thread whose
  // project id is unknown to both lists stays here too. TanStack dedupes
  // these shared queries with `GroupedProjectList`.
  const activeProjectsQuery = useProjects("active");
  const archivedProjectsQuery = useProjects("archived");
  const knownProjectIds = useMemo(() => {
    const activeProjects = activeProjectsQuery.data;
    const archivedProjects = archivedProjectsQuery.data;
    if (
      activeProjectsQuery.isError ||
      archivedProjectsQuery.isError ||
      !activeProjects ||
      !archivedProjects
    ) {
      return null;
    }
    return new Set(
      [...activeProjects, ...archivedProjects].map((project) => project.id),
    );
  }, [
    activeProjectsQuery.data,
    activeProjectsQuery.isError,
    archivedProjectsQuery.data,
    archivedProjectsQuery.isError,
  ]);
  const threadListModel = useMemo(
    () => buildThreadListModel(infiniteThreads?.pages ?? []),
    [infiniteThreads?.pages],
  );
  const { threads } = threadListModel;
  const displayedThreads = useMemo(() => {
    if (
      !threadIdFromPath ||
      threadListModel.displayedThreads.some(
        (thread) => thread.thread_id === threadIdFromPath,
      )
    ) {
      return threadListModel.displayedThreads;
    }
    const activeThread = threadListModel.byId.get(threadIdFromPath);
    return activeThread
      ? [...threadListModel.displayedThreads, activeThread]
      : threadListModel.displayedThreads;
  }, [threadIdFromPath, threadListModel]);
  // In grouped mode, project-assigned threads render under their project
  // header in `ProjectsSection`; this list keeps only unassigned threads —
  // plus any assigned thread whose project cannot render a group (unknown id,
  // or project discovery failed/loading), so no chat silently vanishes.
  const visibleThreads = useMemo(
    () =>
      grouped && knownProjectIds
        ? displayedThreads.filter((thread) => {
            const projectId = projectIdOfThread(thread);
            return projectId === null || !knownProjectIds.has(projectId);
          })
        : displayedThreads,
    [grouped, displayedThreads, knownProjectIds],
  );
  const branchList = useMemo(() => {
    const entries = flattenThreadBranches(visibleThreads);
    return {
      entriesById: new Map(
        entries.map((entry) => [entry.thread.thread_id, entry]),
      ),
      threads: entries.map((entry) => entry.thread),
    };
  }, [visibleThreads]);

  const sentinelRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const element = sentinelRef.current;
    if (!element || !hasNextPage || !threadListModel.canLoadMore) {
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
  }, [
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
    threadListModel.canLoadMore,
  ]);

  // Grouped mode moves project threads under `ProjectsSection`, so this list
  // can be empty while older pages (possibly holding unassigned threads) still
  // exist on the server. Keep the pagination controls mounted then; flat mode
  // keeps the original "empty list renders nothing" behavior.
  if (
    visibleThreads.length === 0 &&
    !(grouped && hasNextPage && threadListModel.canLoadMore)
  ) {
    return null;
  }
  return (
    <SidebarGroup>
      <SidebarGroupLabel>
        {env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY !== "true"
          ? t.sidebar.recentChats
          : t.sidebar.demoChats}
      </SidebarGroupLabel>
      <SidebarGroupContent className="group-data-[collapsible=icon]:pointer-events-none group-data-[collapsible=icon]:-mt-8 group-data-[collapsible=icon]:opacity-0">
        <SidebarMenu>
          {/* Keep pagination at the old list boundary when this switches to virtual rows. */}
          <div
            className="flex w-full flex-col gap-1"
            style={{ overflowAnchor: "none" }}
          >
            <VirtualThreadList
              estimateSize={36}
              gap={4}
              items={branchList.threads}
              scrollParentSelector='[data-sidebar="content"]'
              renderItem={(thread) => (
                <ThreadSidebarItem
                  key={thread.thread_id}
                  thread={thread}
                  isActive={pathOfThread(thread) === pathname}
                  branchEntry={branchList.entriesById.get(thread.thread_id)}
                  recentThreadId={threads[0]?.thread_id}
                />
              )}
            />
            {hasNextPage && threadListModel.canLoadMore && (
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
  );
}
