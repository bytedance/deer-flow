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
import { useEffect, useRef, useState } from "react";
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { ProjectDocumentsSection } from "@/components/workspace/projects/project-documents-section";
import { ProjectThreadsSection } from "@/components/workspace/projects/project-threads-section";
import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import { useI18n } from "@/core/i18n/hooks";
import {
  PROJECTS_CONFIG_DEFAULT,
  useArchiveProject,
  useDeleteProject,
  useInfiniteProjectThreads,
  usePatchProject,
  useProject,
  useProjectsConfig,
  useRestoreProject,
  type Project,
} from "@/core/projects";
import { isStaticWebsiteOnly } from "@/core/static-mode";
import { isIMEComposing } from "@/lib/ime";
import { cn } from "@/lib/utils";

function utf8ByteLength(value: string): number {
  return new TextEncoder().encode(value).length;
}

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
  const projectThreads = threadsQuery.data?.pages.flatMap((page) => page) ?? [];
  const [tab, setTab] = useState("chats");

  useEffect(() => {
    document.title = project?.name
      ? `${project.name} - ${t.pages.appName}`
      : `${t.projects.title} - ${t.pages.appName}`;
  }, [project?.name, t.projects.title, t.pages.appName]);

  // Static demo mode has no Gateway and hides every project surface.
  if (isStaticWebsiteOnly()) {
    return null;
  }

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
                <Tabs
                  value={tab}
                  onValueChange={setTab}
                  className="flex flex-col gap-6"
                >
                  <TabsList aria-label={project.name}>
                    <TabsTrigger value="chats">
                      {t.projects.threads}
                    </TabsTrigger>
                    <TabsTrigger value="documents">
                      {t.projects.documents}
                    </TabsTrigger>
                    <TabsTrigger value="instructions">
                      {t.projects.instructions}
                    </TabsTrigger>
                    <TabsTrigger value="settings">
                      {t.projects.settings}
                    </TabsTrigger>
                  </TabsList>
                  <TabsContent value="chats">
                    <ProjectThreadsSection query={threadsQuery} />
                  </TabsContent>
                  <TabsContent value="documents">
                    <ProjectDocumentsSection
                      project={project}
                      threads={projectThreads}
                    />
                  </TabsContent>
                  <TabsContent value="instructions">
                    {/* Key on the project id only: a route switch must reset
                        the editor, but a save round-trip must NOT remount it
                        — the section reconciles server updates against the
                        last-synced value so keystrokes typed while a save is
                        in flight survive the refetch. */}
                    <ProjectInstructionsSection
                      key={project.id}
                      project={project}
                    />
                  </TabsContent>
                  <TabsContent value="settings">
                    {/* Key on the project id only, same contract as the
                        instructions tab: a rename save round-trip must NOT
                        remount the section — it reconciles server updates
                        against the last-synced name so keystrokes typed
                        while a save is in flight survive the refetch. */}
                    <ProjectSettingsSection
                      key={project.id}
                      project={project}
                    />
                  </TabsContent>
                </Tabs>
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

function ProjectSettingsSection({ project }: { project: Project }) {
  const { t } = useI18n();
  const router = useRouter();
  const patchProject = usePatchProject();
  const archiveProject = useArchiveProject();
  const restoreProject = useRestoreProject();
  const deleteProject = useDeleteProject();

  const [name, setName] = useState(project.name);
  // Same reconciliation contract as the instructions editor: the section is
  // keyed on the project id (not updated_at), so a rename save round-trip —
  // or an archive/restore status flip — does not remount the field and
  // discard in-flight keystrokes. The refetched name overwrites the draft
  // ONLY while the draft still equals the last-synced value.
  const lastSyncedNameRef = useRef(project.name);
  useEffect(() => {
    const serverValue = project.name;
    const synced = lastSyncedNameRef.current;
    lastSyncedNameRef.current = serverValue;
    setName((current) => (current === synced ? serverValue : current));
  }, [project.name]);
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

function ProjectInstructionsSection({ project }: { project: Project }) {
  const { t } = useI18n();
  const patchProject = usePatchProject();
  const configQuery = useProjectsConfig();
  // The gateway enforces ``projects.instructions_max_bytes`` with a 422, so
  // the editor blocks the save before the round trip; while the config
  // endpoint is unavailable (older gateway), fall back to the server
  // default and keep the 422 as the guard of last resort.
  const maxBytes =
    configQuery.data?.instructions_max_bytes ??
    PROJECTS_CONFIG_DEFAULT.instructions_max_bytes;
  const [instructions, setInstructions] = useState(project.instructions);
  // Last server value the draft was synced from. The section is keyed on
  // the project id (not updated_at), so a save's refetch does not remount
  // the editor; instead this effect reconciles: overwrite the draft ONLY
  // while it still equals the last-synced value (the user has not typed
  // since). A diverged draft is kept and the server value becomes the new
  // baseline for future comparisons.
  const lastSyncedRef = useRef(project.instructions);
  useEffect(() => {
    const serverValue = project.instructions;
    const synced = lastSyncedRef.current;
    lastSyncedRef.current = serverValue;
    setInstructions((current) => (current === synced ? serverValue : current));
  }, [project.instructions]);

  const byteCount = utf8ByteLength(instructions);
  const overCap = byteCount > maxBytes;
  const isDirty = instructions !== project.instructions;
  const canSave = isDirty && !overCap && !patchProject.isPending;
  const showSaved = patchProject.isSuccess && !isDirty;

  const handleSave = () => {
    if (!canSave) {
      return;
    }
    patchProject.mutate(
      { projectId: project.id, input: { instructions } },
      {
        onError: (error) => {
          toast.error(
            error instanceof Error && error.message
              ? error.message
              : t.projects.instructionsSaveFailed,
          );
        },
      },
    );
  };

  return (
    <section className="flex flex-col gap-2">
      <label
        htmlFor="project-instructions-input"
        className="text-muted-foreground text-xs"
      >
        {t.projects.instructions}
      </label>
      <Textarea
        id="project-instructions-input"
        className="min-h-40"
        value={instructions}
        onChange={(e) => setInstructions(e.target.value)}
        placeholder={t.projects.instructionsPlaceholder}
        aria-invalid={overCap}
      />
      <div className="flex items-center justify-between gap-2">
        <p
          className={cn(
            "text-xs",
            overCap ? "text-destructive" : "text-muted-foreground",
          )}
        >
          {t.projects.instructionsByteCount(byteCount, maxBytes)}
        </p>
        <div className="flex items-center gap-2">
          {showSaved && (
            <span role="status" className="text-muted-foreground text-xs">
              {t.projects.instructionsSaved}
            </span>
          )}
          <Button variant="outline" disabled={!canSave} onClick={handleSave}>
            {t.common.save}
          </Button>
        </div>
      </div>
      {overCap && (
        <p role="alert" className="text-destructive text-xs">
          {t.projects.instructionsTooLong(maxBytes)}
        </p>
      )}
    </section>
  );
}
