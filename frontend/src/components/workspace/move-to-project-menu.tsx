"use client";

import { Check, FolderInput, FolderMinus, Plus } from "lucide-react";
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
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { useI18n } from "@/core/i18n/hooks";
import { useCreateProject, useProjects } from "@/core/projects";
import { useMoveThreadToProject } from "@/core/threads/hooks";
import type { AgentThread } from "@/core/threads/types";
import { projectIdOfThread } from "@/core/threads/utils";
import { isIMEComposing } from "@/lib/ime";

/**
 * "Move to project" submenu for a thread's dropdown menu: active projects
 * (check mark on the current one), "New project…" (opens the create dialog),
 * and "Remove from project" when the thread is assigned. Archived projects
 * never appear because only the "active" list is queried.
 *
 * Renders ONLY menu content. DropdownMenuContent unmounts its children when
 * the menu closes, so the create dialog lives outside the menu: the
 * "New project…" item delegates to `onNewProject`, and the caller mounts
 * `NewProjectDialog` as a sibling of the DropdownMenu (the same pattern the
 * rename dialog uses in `ThreadSidebarItem`).
 */
export function MoveToProjectMenu({
  thread,
  onNewProject,
  onMoveProject,
}: {
  thread: AgentThread;
  onNewProject: () => void;
  onMoveProject: (projectId: string | null) => void;
}) {
  const { t } = useI18n();
  const { data: projects } = useProjects("active");

  const currentProjectId = projectIdOfThread(thread);

  // Presentational only: the move mutation lives on the persistent
  // `ThreadSidebarItem` (this submenu unmounts when the dropdown closes, so
  // a mutation owned here would lose its error handling on failure).
  const handleMove = useCallback(
    (projectId: string | null) => {
      if (projectId === currentProjectId) {
        return;
      }
      onMoveProject(projectId);
    },
    [currentProjectId, onMoveProject],
  );

  return (
    <DropdownMenuSub>
      <DropdownMenuSubTrigger>
        <FolderInput className="text-muted-foreground" />
        <span>{t.projects.moveToProject}</span>
      </DropdownMenuSubTrigger>
      <DropdownMenuSubContent className="w-56">
        {projects?.map((project) => (
          <DropdownMenuItem
            key={project.id}
            onSelect={() => handleMove(project.id)}
          >
            {project.id === currentProjectId ? (
              <Check className="text-muted-foreground" />
            ) : (
              <span aria-hidden="true" className="size-4 shrink-0" />
            )}
            <span className="truncate">{project.name}</span>
          </DropdownMenuItem>
        ))}
        {projects && projects.length > 0 && <DropdownMenuSeparator />}
        <DropdownMenuItem onSelect={onNewProject}>
          <Plus className="text-muted-foreground" />
          <span>{t.projects.newProject}…</span>
        </DropdownMenuItem>
        {currentProjectId !== null && (
          <DropdownMenuItem onSelect={() => handleMove(null)}>
            <FolderMinus className="text-muted-foreground" />
            <span>{t.projects.removeFromProject}</span>
          </DropdownMenuItem>
        )}
        <DropdownMenuSeparator />
        <DropdownMenuItem disabled>
          <span className="text-xs">{t.projects.moveToProjectHint}</span>
        </DropdownMenuItem>
      </DropdownMenuSubContent>
    </DropdownMenuSub>
  );
}

/**
 * "New project" dialog for the move-to-project flow. Must be mounted
 * OUTSIDE the thread's DropdownMenuContent (as a sibling of the
 * DropdownMenu) so it survives the menu closing. On successful create, the
 * thread is moved into the new project.
 */
export function NewProjectDialog({
  thread,
  open,
  onOpenChange,
}: {
  thread: AgentThread;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { t } = useI18n();
  const { mutate: createProject, isPending: isCreating } = useCreateProject();
  const { mutate: moveThreadToProject } = useMoveThreadToProject();

  const [createName, setCreateName] = useState("");

  const handleOpenChange = useCallback(
    (nextOpen: boolean) => {
      if (!nextOpen) {
        setCreateName("");
      }
      onOpenChange(nextOpen);
    },
    [onOpenChange],
  );

  const handleCreateSubmit = useCallback(() => {
    const name = createName.trim();
    if (!name || isCreating) {
      return;
    }
    createProject(
      { name },
      {
        onSuccess: (project) => {
          handleOpenChange(false);
          moveThreadToProject(
            { threadId: thread.thread_id, projectId: project.id },
            {
              onError: (error) => {
                toast.error(
                  error instanceof Error && error.message
                    ? error.message
                    : t.projects.moveFailed,
                );
              },
            },
          );
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
  }, [
    createProject,
    createName,
    isCreating,
    handleOpenChange,
    moveThreadToProject,
    t.projects.createFailed,
    t.projects.moveFailed,
    thread.thread_id,
  ]);

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
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
          <Button variant="outline" onClick={() => handleOpenChange(false)}>
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
  );
}
