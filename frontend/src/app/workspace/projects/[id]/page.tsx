"use client";

import {
  Archive,
  Folder,
  MessageSquarePlus,
  RotateCcw,
  Trash2,
} from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
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
  Empty,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@/components/ui/empty";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { VirtualThreadList } from "@/components/workspace/thread-list-virtualizer";
import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import { useI18n } from "@/core/i18n/hooks";
import {
  useArchiveProject,
  useDeleteProject,
  useInfiniteProjectThreads,
  usePatchProject,
  useProject,
  useRestoreProject,
  type Project,
  type ProjectThreadsQueryResult,
} from "@/core/projects";
import { pathOfThread } from "@/core/threads/utils";
import { formatTimeAgo } from "@/core/utils/datetime";
import { isIMEComposing } from "@/lib/ime";

function newProjectChatPath(projectId: string): string {
  return `/workspace/chats/new?project=${encodeURIComponent(projectId)}`;
}

export default function ProjectPage() {
  const { t } = useI18n();
  const { id: projectId } = useParams<{ id: string }>();
  const projectQuery = useProject(projectId);
  const project = projectQuery.data;
  // Skip the threads request entirely when the project 404s — the endpoint
  // itself 404s for a missing project, so firing it would be pure noise.
  const threadsQuery = useInfiniteProjectThreads(projectId, {
    enabled: project != null,
  });

  useEffect(() => {
    document.title = project?.name
      ? `${project.name} - ${t.pages.appName}`
      : `${t.projects.title} - ${t.pages.appName}`;
  }, [project?.name, t.projects.title, t.pages.appName]);

  return (
    <WorkspaceContainer>
      <WorkspaceHeader />
      <WorkspaceBody>
        <ScrollArea className="size-full">
          <div className="mx-auto flex w-full max-w-(--container-width-md) flex-col gap-8 p-6 pt-8">
            {projectQuery.isError ? (
              <ProjectNotFoundState />
            ) : project == null ? (
              <div className="text-muted-foreground py-16 text-center text-sm">
                {t.common.loading}
              </div>
            ) : (
              <>
                <ProjectHeader project={project} />
                <ProjectThreadsSection query={threadsQuery} />
                {/* Keying on updated_at re-syncs the rename draft whenever the
                    project changes underneath (e.g. rename round-trip). */}
                <ProjectSettingsSection
                  key={project.updated_at}
                  project={project}
                />
              </>
            )}
          </div>
        </ScrollArea>
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}

function ProjectNotFoundState() {
  const { t } = useI18n();
  return (
    <Empty className="py-16">
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <Folder />
        </EmptyMedia>
        <EmptyTitle>{t.projects.notFound}</EmptyTitle>
      </EmptyHeader>
    </Empty>
  );
}

function ProjectHeader({ project }: { project: Project }) {
  const { t } = useI18n();
  return (
    <header className="flex flex-wrap items-center gap-3">
      <h1 className="min-w-0 flex-1 truncate text-2xl font-semibold">
        {project.name}
      </h1>
      {project.status === "archived" && (
        <Badge variant="secondary">{t.projects.archived}</Badge>
      )}
      {project.status !== "archived" && (
        <Button asChild>
          <Link href={newProjectChatPath(project.id)}>
            <MessageSquarePlus />
            {t.projects.newChat}
          </Link>
        </Button>
      )}
    </header>
  );
}

function ProjectThreadsSection({
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
          // The page scrolls inside this ScrollArea; the list windows rows
          // against its viewport so paging through a long-lived project never
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
                  className={`hover:bg-muted/50 flex min-w-0 items-center gap-2 p-4 transition-colors${index === threads.length - 1 ? "" : "border-b"}`}
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

function ProjectSettingsSection({ project }: { project: Project }) {
  const { t } = useI18n();
  const router = useRouter();
  const patchProject = usePatchProject();
  const archiveProject = useArchiveProject();
  const restoreProject = useRestoreProject();
  const deleteProject = useDeleteProject();

  const [name, setName] = useState(project.name);
  const [isDeleteDialogOpen, setIsDeleteDialogOpen] = useState(false);

  const trimmedName = name.trim();
  const canSave =
    trimmedName.length > 0 &&
    trimmedName !== project.name &&
    !patchProject.isPending;
  const isArchived = project.status === "archived";

  const handleRename = () => {
    if (!canSave) {
      return;
    }
    patchProject.mutate(
      { projectId: project.id, input: { name: trimmedName } },
      {
        onError: (error) => {
          toast.error(
            error instanceof Error && error.message
              ? error.message
              : t.common.renameFailed,
          );
        },
      },
    );
  };

  const handleArchiveToggle = () => {
    const mutation = isArchived ? restoreProject : archiveProject;
    const fallback = isArchived
      ? t.projects.restoreFailed
      : t.projects.archiveFailed;
    mutation.mutate(project.id, {
      onError: (error) => {
        toast.error(
          error instanceof Error && error.message ? error.message : fallback,
        );
      },
    });
  };

  const handleDelete = () => {
    deleteProject.mutate(project.id, {
      onSuccess: () => {
        router.push("/workspace/chats");
      },
      onError: (error) => {
        toast.error(
          error instanceof Error && error.message
            ? error.message
            : t.projects.deleteFailed,
        );
      },
    });
  };

  return (
    <section className="flex flex-col gap-4">
      <h2 className="text-muted-foreground text-sm font-medium">
        {t.projects.settings}
      </h2>
      <div className="flex flex-col gap-2">
        <label
          htmlFor="project-name-input"
          className="text-muted-foreground text-xs"
        >
          {t.projects.namePlaceholder}
        </label>
        <div className="flex items-center gap-2">
          <Input
            id="project-name-input"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={t.projects.namePlaceholder}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !isIMEComposing(e)) {
                e.preventDefault();
                handleRename();
              }
            }}
          />
          <Button variant="outline" disabled={!canSave} onClick={handleRename}>
            {t.common.save}
          </Button>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Button
          variant="outline"
          disabled={archiveProject.isPending || restoreProject.isPending}
          onClick={handleArchiveToggle}
        >
          {isArchived ? <RotateCcw /> : <Archive />}
          {isArchived ? t.projects.restore : t.projects.archive}
        </Button>
        <Button
          variant="destructive"
          onClick={() => setIsDeleteDialogOpen(true)}
        >
          <Trash2 />
          {t.projects.deleteProject}
        </Button>
      </div>
      <Dialog open={isDeleteDialogOpen} onOpenChange={setIsDeleteDialogOpen}>
        <DialogContent className="sm:max-w-[425px]">
          <DialogHeader>
            <DialogTitle>{t.projects.deleteProject}</DialogTitle>
            <DialogDescription>
              {t.projects.deleteProjectConfirm}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setIsDeleteDialogOpen(false)}
            >
              {t.common.cancel}
            </Button>
            <Button
              variant="destructive"
              disabled={deleteProject.isPending}
              onClick={handleDelete}
            >
              {t.common.delete}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  );
}
