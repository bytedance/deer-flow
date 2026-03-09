import { Check, FolderPlus, Plus } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { useI18n } from "@/core/i18n/hooks";
import type { Project } from "@/core/projects/types";
import { cn } from "@/lib/utils";

interface AssignToProjectDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  currentProjectId: string | null | undefined;
  projects: Project[];
  onAssign: (projectId: string | null) => void;
  onCreateProject: (name: string) => void;
}

export function AssignToProjectDialog({
  open,
  onOpenChange,
  currentProjectId,
  projects,
  onAssign,
  onCreateProject,
}: AssignToProjectDialogProps) {
  const { t } = useI18n();
  const [isCreating, setIsCreating] = useState(false);
  const [newProjectName, setNewProjectName] = useState("");

  const handleAssign = (projectId: string | null) => {
    onAssign(projectId);
    onOpenChange(false);
  };

  const handleCreate = () => {
    const name = newProjectName.trim();
    if (name) {
      onCreateProject(name);
      setNewProjectName("");
      setIsCreating(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[360px]">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <FolderPlus className="size-4" />
            {t.sidebar.addToProject}
          </DialogTitle>
        </DialogHeader>
        <div className="flex max-h-[300px] flex-col gap-0.5 overflow-y-auto py-2">
          {/* Default project (unassigned) */}
          <button
            className={cn(
              "flex w-full items-center justify-between rounded-md px-3 py-2 text-left text-sm transition-colors",
              "hover:bg-accent",
              !currentProjectId && "bg-accent",
            )}
            onClick={() => handleAssign(null)}
          >
            <span>{t.sidebar.defaultProject}</span>
            {!currentProjectId && (
              <Check className="text-primary size-4" />
            )}
          </button>

          {/* User projects */}
          {projects.map((project) => (
            <button
              key={project.project_id}
              className={cn(
                "flex w-full items-center justify-between rounded-md px-3 py-2 text-left text-sm transition-colors",
                "hover:bg-accent",
                currentProjectId === project.project_id && "bg-accent",
              )}
              onClick={() => handleAssign(project.project_id)}
            >
              <span>{project.name}</span>
              {currentProjectId === project.project_id && (
                <Check className="text-primary size-4" />
              )}
            </button>
          ))}
        </div>

        <DialogFooter className="flex-col gap-2 sm:flex-col">
          {isCreating ? (
            <div className="flex items-center gap-2">
              <Input
                autoFocus
                value={newProjectName}
                onChange={(e) => setNewProjectName(e.target.value)}
                placeholder={t.sidebar.projectName}
                className="h-8 text-sm"
                onKeyDown={(e) => {
                  if (e.key === "Enter") handleCreate();
                  if (e.key === "Escape") {
                    setIsCreating(false);
                    setNewProjectName("");
                  }
                }}
              />
              <Button size="sm" onClick={handleCreate} className="h-8">
                {t.common.create}
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  setIsCreating(false);
                  setNewProjectName("");
                }}
                className="h-8"
              >
                {t.common.cancel}
              </Button>
            </div>
          ) : (
            <Button
              variant="ghost"
              size="sm"
              className="w-full justify-start"
              onClick={() => setIsCreating(true)}
            >
              <Plus className="size-4" />
              {t.sidebar.newProject}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
