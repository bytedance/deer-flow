import {
  ChevronDown,
  MoreHorizontal,
  Pencil,
  Plus,
  Trash2,
} from "lucide-react";
import { useMemo, useState } from "react";

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
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { SidebarMenu } from "@/components/ui/sidebar";
import { useI18n } from "@/core/i18n/hooks";
import type { Project } from "@/core/projects/types";
import type { AgentThread } from "@/core/threads/types";
import { cn } from "@/lib/utils";

import { ThreadItem } from "./thread-item";

interface ProjectGroupedThreadListProps {
  threads: AgentThread[];
  projects: Project[];
  onRename: (threadId: string, currentTitle: string) => void;
  onDelete: (threadId: string) => void;
  onShare: (threadId: string) => void;
  onAssignToProject: (threadId: string) => void;
  onCreateProject: (name: string) => void;
  onRenameProject: (projectId: string, name: string) => void;
  onDeleteProject: (projectId: string) => void;
}

interface ProjectGroup {
  projectId: string | null;
  name: string;
  threads: AgentThread[];
}

export function ProjectGroupedThreadList({
  threads,
  projects,
  onRename,
  onDelete,
  onShare,
  onAssignToProject,
  onCreateProject,
  onRenameProject,
  onDeleteProject,
}: ProjectGroupedThreadListProps) {
  const { t } = useI18n();
  const [collapsedIds, setCollapsedIds] = useState<Set<string>>(new Set());

  // Dialog states for project operations
  const [renameDialog, setRenameDialog] = useState<{
    open: boolean;
    projectId: string;
    currentName: string;
  }>({ open: false, projectId: "", currentName: "" });
  const [renameValue, setRenameValue] = useState("");

  const [deleteDialog, setDeleteDialog] = useState<{
    open: boolean;
    projectId: string;
  }>({ open: false, projectId: "" });

  const [createDialog, setCreateDialog] = useState(false);
  const [createName, setCreateName] = useState("");

  const groups = useMemo(() => {
    const result: ProjectGroup[] = [];

    // Default group (unassigned threads)
    const defaultThreads = threads.filter(
      (t) => !t.project_id,
    );
    result.push({
      projectId: null,
      name: t.sidebar.defaultProject,
      threads: defaultThreads.sort(
        (a, b) =>
          new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime(),
      ),
    });

    // Project groups
    for (const project of projects) {
      const projectThreads = threads.filter(
        (th) => th.project_id === project.project_id,
      );
      result.push({
        projectId: project.project_id,
        name: project.name,
        threads: projectThreads.sort(
          (a, b) =>
            new Date(b.updated_at).getTime() -
            new Date(a.updated_at).getTime(),
        ),
      });
    }

    return result;
  }, [threads, projects, t]);

  const toggleCollapsed = (id: string) => {
    setCollapsedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  const handleRenameSubmit = () => {
    const name = renameValue.trim();
    if (name && renameDialog.projectId) {
      onRenameProject(renameDialog.projectId, name);
      setRenameDialog({ open: false, projectId: "", currentName: "" });
    }
  };

  const handleDeleteConfirm = () => {
    if (deleteDialog.projectId) {
      onDeleteProject(deleteDialog.projectId);
      setDeleteDialog({ open: false, projectId: "" });
    }
  };

  const handleCreateSubmit = () => {
    const name = createName.trim();
    if (name) {
      onCreateProject(name);
      setCreateName("");
      setCreateDialog(false);
    }
  };

  return (
    <>
      <div className="px-2 pt-1 pb-1">
        <Button
          variant="ghost"
          size="sm"
          className="text-muted-foreground hover:text-foreground h-7 w-full justify-start gap-1.5 text-xs"
          onClick={() => setCreateDialog(true)}
        >
          <Plus className="size-3.5" />
          {t.sidebar.newProject}
        </Button>
      </div>

      {groups.map((group) => {
        const groupKey = group.projectId ?? "__default__";
        const isOpen = !collapsedIds.has(groupKey);

        // Hide empty project groups (but always show Default)
        if (group.threads.length === 0 && group.projectId !== null) {
          return null;
        }

        return (
          <Collapsible
            key={groupKey}
            open={isOpen}
            onOpenChange={() => toggleCollapsed(groupKey)}
            className="px-2"
          >
            <div className="group/project flex items-center gap-0.5">
              <CollapsibleTrigger className="flex flex-1 items-center gap-1 rounded-md px-1.5 py-1 text-xs font-medium transition-colors hover:bg-accent">
                <ChevronDown
                  className={cn(
                    "text-muted-foreground size-3.5 shrink-0 transition-transform duration-200",
                    !isOpen && "-rotate-90",
                  )}
                />
                <span className="text-muted-foreground truncate">
                  {group.name}
                </span>
                <span className="text-muted-foreground/50 ml-auto text-[10px]">
                  {group.threads.length}
                </span>
              </CollapsibleTrigger>

              {/* Project actions (not for Default) */}
              {group.projectId !== null && (
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <button className="text-muted-foreground hover:text-foreground rounded-md p-0.5 opacity-0 transition-opacity group-hover/project:opacity-100">
                      <MoreHorizontal className="size-3.5" />
                    </button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent
                    className="w-40 rounded-lg"
                    side="right"
                    align="start"
                  >
                    <DropdownMenuItem
                      onSelect={() => {
                        setRenameValue(group.name);
                        setRenameDialog({
                          open: true,
                          projectId: group.projectId!,
                          currentName: group.name,
                        });
                      }}
                    >
                      <Pencil className="text-muted-foreground" />
                      <span>{t.sidebar.renameProject}</span>
                    </DropdownMenuItem>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem
                      onSelect={() =>
                        setDeleteDialog({
                          open: true,
                          projectId: group.projectId!,
                        })
                      }
                    >
                      <Trash2 className="text-muted-foreground" />
                      <span>{t.sidebar.deleteProject}</span>
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              )}
            </div>

            <CollapsibleContent>
              <SidebarMenu className="pl-2">
                <div className="flex w-full flex-col gap-0.5">
                  {group.threads.map((thread) => (
                    <ThreadItem
                      key={thread.thread_id}
                      thread={thread}
                      onRename={onRename}
                      onDelete={onDelete}
                      onShare={onShare}
                      onAssignToProject={onAssignToProject}
                    />
                  ))}
                </div>
              </SidebarMenu>
            </CollapsibleContent>
          </Collapsible>
        );
      })}

      {/* Rename Project Dialog */}
      <Dialog
        open={renameDialog.open}
        onOpenChange={(open) =>
          setRenameDialog((prev) => ({ ...prev, open }))
        }
      >
        <DialogContent className="sm:max-w-[425px]">
          <DialogHeader>
            <DialogTitle>{t.sidebar.renameProject}</DialogTitle>
          </DialogHeader>
          <div className="py-4">
            <Input
              value={renameValue}
              onChange={(e) => setRenameValue(e.target.value)}
              placeholder={t.sidebar.projectName}
              onKeyDown={(e) => {
                if (e.key === "Enter") handleRenameSubmit();
              }}
            />
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() =>
                setRenameDialog({ open: false, projectId: "", currentName: "" })
              }
            >
              {t.common.cancel}
            </Button>
            <Button onClick={handleRenameSubmit}>{t.common.save}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete Project Confirmation Dialog */}
      <Dialog
        open={deleteDialog.open}
        onOpenChange={(open) =>
          setDeleteDialog((prev) => ({ ...prev, open }))
        }
      >
        <DialogContent className="sm:max-w-[425px]">
          <DialogHeader>
            <DialogTitle>{t.sidebar.deleteProject}</DialogTitle>
          </DialogHeader>
          <p className="text-muted-foreground py-4 text-sm">
            {t.sidebar.deleteProjectConfirm}
          </p>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() =>
                setDeleteDialog({ open: false, projectId: "" })
              }
            >
              {t.common.cancel}
            </Button>
            <Button variant="destructive" onClick={handleDeleteConfirm}>
              {t.common.delete}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Create Project Dialog */}
      <Dialog open={createDialog} onOpenChange={setCreateDialog}>
        <DialogContent className="sm:max-w-[425px]">
          <DialogHeader>
            <DialogTitle>{t.sidebar.createProject}</DialogTitle>
          </DialogHeader>
          <div className="py-4">
            <Input
              autoFocus
              value={createName}
              onChange={(e) => setCreateName(e.target.value)}
              placeholder={t.sidebar.projectName}
              onKeyDown={(e) => {
                if (e.key === "Enter") handleCreateSubmit();
              }}
            />
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => {
                setCreateDialog(false);
                setCreateName("");
              }}
            >
              {t.common.cancel}
            </Button>
            <Button onClick={handleCreateSubmit}>{t.common.create}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
