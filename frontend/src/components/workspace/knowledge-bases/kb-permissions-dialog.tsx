"use client";

import { ShieldIcon, Trash2Icon } from "@/components/ui/icons";
import { useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useI18n } from "@/core/i18n/hooks";
import {
  useGrantPermission,
  usePermissions,
  useRevokePermission,
} from "@/core/knowledge-base";
import type { KBPermissionRole, KnowledgeBase } from "@/core/knowledge-base";

interface KBPermissionsDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  knowledgeBase: KnowledgeBase;
}

export function KBPermissionsDialog({
  open,
  onOpenChange,
  knowledgeBase,
}: KBPermissionsDialogProps) {
  const { t } = useI18n();
  const { permissions, isLoading } = usePermissions(knowledgeBase.id, {
    enabled: open,
  });
  const grantMutation = useGrantPermission(knowledgeBase.id);
  const revokeMutation = useRevokePermission(knowledgeBase.id);
/* PLACEHOLDER_REST */

  const [userId, setUserId] = useState("");
  const [role, setRole] = useState<KBPermissionRole>("viewer");

  function roleLabel(r: string) {
    switch (r) {
      case "viewer":
        return t.knowledgeBase.roleViewer;
      case "editor":
        return t.knowledgeBase.roleEditor;
      case "admin":
        return t.knowledgeBase.roleAdmin;
      default:
        return r;
    }
  }

  async function handleGrant() {
    if (!userId.trim()) return;
    try {
      await grantMutation.mutateAsync({ user_id: userId.trim(), role });
      toast.success(t.knowledgeBase.grantSuccess);
      setUserId("");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    }
  }

  async function handleRevoke(targetUserId: string) {
    try {
      await revokeMutation.mutateAsync(targetUserId);
      toast.success(t.knowledgeBase.revokeSuccess);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <ShieldIcon className="h-5 w-5" />
            {t.knowledgeBase.permissions}
          </DialogTitle>
          <DialogDescription>
            {t.knowledgeBase.permissionsDescription}
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-4 py-2">
          {/* Grant form */}
          <div className="flex items-end gap-2">
            <div className="flex-1">
              <Input
                value={userId}
                onChange={(e) => setUserId(e.target.value)}
                placeholder={t.knowledgeBase.userIdPlaceholder}
              />
            </div>
            <Select
              value={role}
              onValueChange={(v) => setRole(v as KBPermissionRole)}
            >
              <SelectTrigger className="w-28">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="viewer">
                  {t.knowledgeBase.roleViewer}
                </SelectItem>
                <SelectItem value="editor">
                  {t.knowledgeBase.roleEditor}
                </SelectItem>
                <SelectItem value="admin">
                  {t.knowledgeBase.roleAdmin}
                </SelectItem>
              </SelectContent>
            </Select>
            <Button
              size="sm"
              onClick={handleGrant}
              disabled={!userId.trim() || grantMutation.isPending}
            >
              {t.knowledgeBase.grantPermission}
            </Button>
          </div>

          {/* Permission list */}
          <div className="flex flex-col gap-2">
            {isLoading ? (
              <p className="text-muted-foreground text-sm">
                {t.common.loading}
              </p>
            ) : permissions.length === 0 ? (
              <p className="text-muted-foreground text-sm">
                {t.knowledgeBase.noPermissions}
              </p>
            ) : (
              permissions.map((perm) => (
                <div
                  key={perm.id}
                  className="flex items-center justify-between rounded-md border px-3 py-2"
                >
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium">{perm.user_id}</span>
                    <Badge variant="secondary" className="text-xs">
                      {roleLabel(perm.role)}
                    </Badge>
                  </div>
                  <Button
                    size="icon"
                    variant="ghost"
                    className="text-destructive hover:text-destructive h-7 w-7"
                    onClick={() => handleRevoke(perm.user_id)}
                    disabled={revokeMutation.isPending}
                    title={t.knowledgeBase.revokePermission}
                  >
                    <Trash2Icon className="h-3.5 w-3.5" />
                  </Button>
                </div>
              ))
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
