"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
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
import { Textarea } from "@/components/ui/textarea";
import { useAuth } from "@/core/auth/AuthProvider";
import { useI18n } from "@/core/i18n/hooks";
import {
  useCreateKnowledgeBase,
  useUpdateKnowledgeBase,
} from "@/core/knowledge-base";
import type { KBVisibility, KnowledgeBase } from "@/core/knowledge-base";

interface KBFormDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  knowledgeBase?: KnowledgeBase;
}

export function KBFormDialog({
  open,
  onOpenChange,
  knowledgeBase,
}: KBFormDialogProps) {
  const { t } = useI18n();
  const { user } = useAuth();
  const createMutation = useCreateKnowledgeBase();
  const updateMutation = useUpdateKnowledgeBase();
  const isEdit = !!knowledgeBase;

  const canCreateTenant =
    user?.system_role === "superadmin" || user?.system_role === "tenant_admin";
  const canCreatePublic = user?.system_role === "superadmin";

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [visibility, setVisibility] = useState<KBVisibility>("private");

  useEffect(() => {
    if (open) {
      setName(knowledgeBase?.name ?? "");
      setDescription(knowledgeBase?.description ?? "");
      setVisibility(knowledgeBase?.visibility ?? "private");
    }
  }, [open, knowledgeBase]);
  async function handleSubmit() {
    if (!name.trim()) return;
    try {
      if (isEdit) {
        await updateMutation.mutateAsync({
          id: knowledgeBase.id,
          request: {
            name: name.trim(),
            description: description.trim() || null,
          },
        });
      } else {
        await createMutation.mutateAsync({
          name: name.trim(),
          description: description.trim() || undefined,
          visibility,
        });
      }
      onOpenChange(false);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    }
  }

  const isPending = createMutation.isPending || updateMutation.isPending;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {isEdit ? t.common.edit : t.knowledgeBase.newKnowledgeBase}
          </DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-4 py-4">
          <div className="flex flex-col gap-2">
            <label htmlFor="kb-name" className="text-sm font-medium">{t.knowledgeBase.name}</label>
            <Input
              id="kb-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t.knowledgeBase.namePlaceholder}
            />
          </div>
          <div className="flex flex-col gap-2">
            <label htmlFor="kb-desc" className="text-sm font-medium">{t.knowledgeBase.descriptionLabel}</label>
            <Textarea
              id="kb-desc"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder={t.knowledgeBase.descriptionPlaceholder}
              rows={3}
            />
          </div>
          {!isEdit && (
            <div className="flex flex-col gap-2">
              <label htmlFor="kb-visibility" className="text-sm font-medium">{t.knowledgeBase.visibility}</label>
              <Select
                value={visibility}
                onValueChange={(v) => setVisibility(v as KBVisibility)}
              >
                <SelectTrigger id="kb-visibility">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="private">{t.knowledgeBase.visibilityPrivate}</SelectItem>
                  <SelectItem value="tenant" disabled={!canCreateTenant}>
                    {t.knowledgeBase.visibilityTenant}
                    {!canCreateTenant && (
                      <span className="text-muted-foreground ml-2 text-xs">
                        ({t.knowledgeBase.visibilityHintTenant})
                      </span>
                    )}
                  </SelectItem>
                  <SelectItem value="public" disabled={!canCreatePublic}>
                    {t.knowledgeBase.visibilityPublic}
                    {!canCreatePublic && (
                      <span className="text-muted-foreground ml-2 text-xs">
                        ({t.knowledgeBase.visibilityHintPublic})
                      </span>
                    )}
                  </SelectItem>
                </SelectContent>
              </Select>
            </div>
          )}
        </div>
        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={isPending}
          >
            {t.common.cancel}
          </Button>
          <Button
            onClick={handleSubmit}
            disabled={isPending || !name.trim()}
          >
            {isPending
              ? isEdit
                ? t.knowledgeBase.saving
                : t.knowledgeBase.creating
              : isEdit
                ? t.knowledgeBase.save
                : t.knowledgeBase.create}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
