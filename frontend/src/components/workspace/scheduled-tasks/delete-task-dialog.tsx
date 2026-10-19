"use client";

import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useI18n } from "@/core/i18n/hooks";
import { useDeleteScheduledTask } from "@/core/scheduled-tasks/hooks";
import type { ScheduledTask } from "@/core/scheduled-tasks/types";

import { fill } from "./shared";

export function DeleteTaskDialog({
  task,
  open,
  onOpenChange,
  onDeleted,
}: {
  task: Pick<ScheduledTask, "id" | "title">;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onDeleted?: () => void;
}) {
  const { t } = useI18n();
  const st = t.scheduledTasks;
  const deleteTask = useDeleteScheduledTask();
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {fill(st.actions.deleteTitle, { title: task.title })}
          </DialogTitle>
          <DialogDescription>{st.actions.deleteBody}</DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={deleteTask.isPending}
          >
            {t.common.cancel}
          </Button>
          <Button
            variant="destructive"
            disabled={deleteTask.isPending}
            onClick={() =>
              deleteTask.mutate(task.id, {
                onSuccess: () => {
                  toast.success(st.feedback.deleted);
                  onOpenChange(false);
                  onDeleted?.();
                },
              })
            }
          >
            {deleteTask.isPending ? t.common.loading : st.actions.delete}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
