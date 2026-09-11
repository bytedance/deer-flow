"use client";

import {
  Archive,
  ChevronRight,
  Folder,
  FolderTree,
  List,
  Plus,
} from "lucide-react";
import Link from "next/link";
import { useParams, usePathname } from "next/navigation";
import { useCallback, useMemo, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
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
import { useI18n } from "@/core/i18n/hooks";
import { useCreateProject, useProjects, type Project } from "@/core/projects";
import { useLocalSettings } from "@/core/settings";
import { isStaticWebsiteOnly } from "@/core/static-mode";
import { useInfiniteThreads } from "@/core/threads/hooks";
import { flattenThreadBranches } from "@/core/threads/thread-branch-tree";
import { buildThreadListModel } from "@/core/threads/thread-list-model";
import type { AgentThread } from "@/core/threads/types";
import { pathOfThread, projectIdOfThread } from "@/core/threads/utils";
import { env } from "@/env";
import { isIMEComposing } from "@/lib/ime";

import { ThreadSidebarItem } from "./recent-chat-list";

function projectPath(projectId: string): string {
  return `/workspace/projects/${projectId}`;
}

function ProjectThreadGroup({
  project,
  threads,
  recentThreadId,
}: {
  project: Project;
  threads: readonly AgentThread[];
  /** Global most-recent thread id — mirrors flat mode's `threads[0]?.thread_id`. */
  recentThreadId: string | undefined;
}) {
  const pathname = usePathname();
  const [open, setOpen] = useState(true);
  const href = projectPath(project.id);
  const branchEntries = useMemo(
    () => flattenThreadBranches([...threads]),
    [threads],
  );
  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <SidebarMenuItem>
        <SidebarMenuButton asChild isActive={pathname === href}>
          <Link href={href} title={project.name}>
            <Folder />
            <span className="min-w-0 truncate">{project.name}</span>
          </Link>
        </SidebarMenuButton>
        <CollapsibleTrigger asChild>
          <SidebarMenuAction
            aria-label={project.name}
            className="[&>svg]:transition-transform [&[data-state=open]>svg]:rotate-90"
          >
            <ChevronRight />
          </SidebarMenuAction>
        </CollapsibleTrigger>
      </SidebarMenuItem>
      <CollapsibleContent>
        <SidebarMenu className="border-sidebar-border ml-4 border-l pl-2">
          {branchEntries.map((entry) => (
            <ThreadSidebarItem
              key={entry.thread.thread_id}
              thread={entry.thread}
              isActive={pathOfThread(entry.thread) === pathname}
              branchEntry={entry}
              recentThreadId={recentThreadId}
            />
          ))}
        </SidebarMenu>
      </CollapsibleContent>
    </Collapsible>
  );
}

function ArchivedProjectsGroup({
  projects,
  threadsByProject,
  recentThreadId,
}: {
  projects: readonly Project[];
  threadsByProject: ReadonlyMap<string, readonly AgentThread[]>;
  recentThreadId: string | undefined;
}) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <SidebarMenuItem>
        <CollapsibleTrigger asChild>
          <SidebarMenuButton>
            <Archive />
            <span className="min-w-0 truncate">{t.projects.archived}</span>
            <ChevronRight className="ml-auto transition-transform [[data-state=open]>&]:rotate-90" />
          </SidebarMenuButton>
        </CollapsibleTrigger>
      </SidebarMenuItem>
      <CollapsibleContent>
        <SidebarMenu className="border-sidebar-border ml-4 border-l pl-2">
          {projects.map((project) => (
            <ProjectThreadGroup
              key={project.id}
              project={project}
              threads={threadsByProject.get(project.id) ?? []}
              recentThreadId={recentThreadId}
            />
          ))}
        </SidebarMenu>
      </CollapsibleContent>
    </Collapsible>
  );
}

/**
 * Grouped mode: active projects as collapsible headers with their recent
 * threads (grouped client-side from the already-fetched infinite thread
 * pages), plus a collapsed "Archived" section at the bottom.
 */
function GroupedProjectList() {
  const { data: activeProjects } = useProjects("active");
  const { data: archivedProjects } = useProjects("archived");
  const { data: infiniteThreads } = useInfiniteThreads({
    archived:
      env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true" ? undefined : false,
  });
  const { thread_id: threadIdFromPath } = useParams<{
    thread_id: string;
    agent_name?: string;
  }>();
  const threadListModel = useMemo(
    () => buildThreadListModel(infiniteThreads?.pages ?? []),
    [infiniteThreads?.pages],
  );
  // Same value flat mode passes to `ThreadSidebarItem` — the global most-recent
  // thread, NOT the capped displayedThreads or any group-local first entry.
  const globalRecentThreadId = threadListModel.threads[0]?.thread_id;
  // Mirror `RecentChatList`'s active-thread exception: the path-active thread
  // is appended even when it falls beyond the unpinned display cap, so it
  // must join the partition input too — otherwise an active assigned chat
  // renders in neither the flat list nor its project group.
  const partitionableThreads = useMemo(() => {
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
  const threadsByProject = useMemo(() => {
    const grouped = new Map<string, AgentThread[]>();
    for (const thread of partitionableThreads) {
      const projectId = projectIdOfThread(thread);
      if (projectId === null) {
        continue;
      }
      const projectThreads = grouped.get(projectId);
      if (projectThreads) {
        projectThreads.push(thread);
      } else {
        grouped.set(projectId, [thread]);
      }
    }
    return grouped;
  }, [partitionableThreads]);

  if (
    (!activeProjects || activeProjects.length === 0) &&
    (!archivedProjects || archivedProjects.length === 0)
  ) {
    return null;
  }
  return (
    <SidebarMenu>
      {activeProjects?.map((project) => (
        <ProjectThreadGroup
          key={project.id}
          project={project}
          threads={threadsByProject.get(project.id) ?? []}
          recentThreadId={globalRecentThreadId}
        />
      ))}
      {archivedProjects && archivedProjects.length > 0 && (
        <ArchivedProjectsGroup
          projects={archivedProjects}
          threadsByProject={threadsByProject}
          recentThreadId={globalRecentThreadId}
        />
      )}
    </SidebarMenu>
  );
}

export function ProjectsSection() {
  const { t } = useI18n();
  const [settings, setSettings] = useLocalSettings();
  const groupByProject = settings.projectsDisplayMode === "grouped";
  const { mutate: createProject, isPending: isCreating } = useCreateProject();

  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [createName, setCreateName] = useState("");

  const handleCreateSubmit = useCallback(() => {
    const name = createName.trim();
    if (!name || isCreating) {
      return;
    }
    createProject(
      { name },
      {
        onSuccess: () => {
          setCreateDialogOpen(false);
          setCreateName("");
        },
        onError: (error) => {
          toast.error(
            error instanceof Error && error.message
              ? error.message
              : t.projects.createFailed,
          );
        },
      },
    );
  }, [createProject, createName, isCreating, t.projects.createFailed]);

  // Static-demo mode has no Gateway and no projects: hide the whole section
  // (New project button, grouped toggle, and groups are all dead actions).
  if (isStaticWebsiteOnly()) {
    return null;
  }

  return (
    <SidebarGroup>
      <SidebarGroupLabel className="justify-between pr-1">
        <span>{t.projects.title}</span>
        <span className="flex items-center gap-0.5">
          <Button
            variant="ghost"
            size="icon"
            className="size-5 [&>svg]:size-3.5"
            title={
              groupByProject
                ? t.projects.switchToFlat
                : t.projects.switchToGrouped
            }
            aria-label={
              groupByProject
                ? t.projects.switchToFlat
                : t.projects.switchToGrouped
            }
            onClick={() =>
              setSettings(
                "projectsDisplayMode",
                groupByProject ? "flat" : "grouped",
              )
            }
            data-testid="projects-display-mode-toggle"
          >
            {groupByProject ? <FolderTree /> : <List />}
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="size-5 [&>svg]:size-3.5"
            title={t.projects.newProject}
            aria-label={t.projects.newProject}
            onClick={() => setCreateDialogOpen(true)}
            data-testid="projects-new-project-button"
          >
            <Plus />
          </Button>
        </span>
      </SidebarGroupLabel>
      {groupByProject && (
        <SidebarGroupContent className="group-data-[collapsible=icon]:pointer-events-none group-data-[collapsible=icon]:-mt-8 group-data-[collapsible=icon]:opacity-0">
          <GroupedProjectList />
        </SidebarGroupContent>
      )}

      {/* New project dialog */}
      <Dialog open={createDialogOpen} onOpenChange={setCreateDialogOpen}>
        <DialogContent className="sm:max-w-[425px]">
          <DialogHeader>
            <DialogTitle>{t.projects.newProject}</DialogTitle>
          </DialogHeader>
          <div className="py-4">
            <Input
              value={createName}
              onChange={(e) => setCreateName(e.target.value)}
              placeholder={t.projects.namePlaceholder}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !isIMEComposing(e)) {
                  e.preventDefault();
                  handleCreateSubmit();
                }
              }}
            />
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setCreateDialogOpen(false)}
            >
              {t.common.cancel}
            </Button>
            <Button
              onClick={handleCreateSubmit}
              disabled={!createName.trim() || isCreating}
            >
              {t.projects.create}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </SidebarGroup>
  );
}
