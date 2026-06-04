"use client";

import { Loader2 } from "@/components/ui/icons";
import { useCallback, useState } from "react";
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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import {
  applyResolvedAuthError,
  resolveAuthError,
} from "@/core/auth/api-error";
import { useI18n } from "@/core/i18n/hooks";
import { exportTemplatePackage, publishToMarketplace } from "@/core/marketplace/api";

interface EditorActionsDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  templateId: string;
  mode: "publish" | "export";
}

export function EditorActionsDialog({
  open,
  onOpenChange,
  templateId,
  mode,
}: EditorActionsDialogProps) {
  if (mode === "publish") {
    return (
      <PublishToMarketplaceDialog
        open={open}
        onOpenChange={onOpenChange}
        templateId={templateId}
      />
    );
  }

  return (
    <ExportTemplateDialog
      open={open}
      onOpenChange={onOpenChange}
      templateId={templateId}
    />
  );
}

function PublishToMarketplaceDialog({
  open,
  onOpenChange,
  templateId,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  templateId: string;
}) {
  const { t } = useI18n();
  const [displayName, setDisplayName] = useState("");
  const [description, setDescription] = useState("");
  const [visibility, setVisibility] = useState("tenant");
  const [category, setCategory] = useState("");
  const [tags, setTags] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSubmit = useCallback(async () => {
    if (!displayName.trim()) {
      toast.error(t.editor.displayNameRequired);
      return;
    }

    setIsSubmitting(true);
    try {
      const result = await publishToMarketplace(templateId, {
        display_name: displayName,
        description,
        visibility,
        category: category || undefined,
        tags: tags
          .split(",")
          .map((tag) => tag.trim())
          .filter(Boolean),
      });
      toast.success(result.message || t.editor.publishSuccessMsg);
      onOpenChange(false);
    } catch (err) {
      const authError = resolveAuthError(err, t.editor.publish);
      if (authError) {
        toast.error(authError.message);
        applyResolvedAuthError(authError, window.location.pathname);
        return;
      }
      toast.error((err as Error).message || t.editor.publishFailedMsg);
    } finally {
      setIsSubmitting(false);
    }
  }, [
    category,
    description,
    displayName,
    onOpenChange,
    t.editor.displayNameRequired,
    t.editor.publish,
    t.editor.publishFailedMsg,
    t.editor.publishSuccessMsg,
    tags,
    templateId,
    visibility,
  ]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t.editor.publishToMarketplace}</DialogTitle>
          <DialogDescription>
            {t.editor.publishToMarketplaceDescription}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div>
            <Label>{t.editor.displayNameLabel} *</Label>
            <Input
              value={displayName}
              onChange={(event) => setDisplayName(event.target.value)}
              placeholder={t.editor.templateDisplayNamePlaceholder}
            />
          </div>

          <div>
            <Label>{t.editor.descriptionLabel}</Label>
            <Textarea
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              placeholder={t.editor.templateDescriptionPlaceholder}
              rows={3}
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label>{t.editor.visibilityLabel}</Label>
              <Select value={visibility} onValueChange={setVisibility}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="tenant">
                    {t.marketplace.visibilityTenant}
                  </SelectItem>
                  <SelectItem value="builtin">
                    {t.marketplace.visibilityBuiltin}
                  </SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label>{t.editor.categoryLabel}</Label>
              <Input
                value={category}
                onChange={(event) => setCategory(event.target.value)}
                placeholder=""
              />
            </div>
          </div>

          <div>
            <Label>{t.editor.tagsLabel}</Label>
            <Input
              value={tags}
              onChange={(event) => setTags(event.target.value)}
              placeholder=""
            />
            <p className="mt-0.5 text-[10px] text-muted-foreground">
              {t.editor.tagsHint}
            </p>
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t.common.cancel}
          </Button>
          <Button onClick={handleSubmit} disabled={isSubmitting}>
            {isSubmitting ? (
              <Loader2 className="mr-1 h-4 w-4 animate-spin" />
            ) : null}
            {t.editor.publish}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function ExportTemplateDialog({
  open,
  onOpenChange,
  templateId,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  templateId: string;
}) {
  const { t } = useI18n();
  const [isExporting, setIsExporting] = useState(false);

  const handleExport = useCallback(async () => {
    setIsExporting(true);
    try {
      const blob = await exportTemplatePackage(templateId);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `${templateId}.template`;
      anchor.click();
      URL.revokeObjectURL(url);
      toast.success(t.editor.exportSuccess);
      onOpenChange(false);
    } catch (err) {
      const authError = resolveAuthError(err, t.common.export);
      if (authError) {
        toast.error(authError.message);
        applyResolvedAuthError(authError, window.location.pathname);
        return;
      }
      toast.error((err as Error).message || t.editor.exportFailed);
    } finally {
      setIsExporting(false);
    }
  }, [
    onOpenChange,
    t.common.export,
    t.editor.exportFailed,
    t.editor.exportSuccess,
    templateId,
  ]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>{t.editor.exportTemplateTitle}</DialogTitle>
          <DialogDescription>
            {t.editor.exportTemplateDescription}
          </DialogDescription>
        </DialogHeader>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t.common.cancel}
          </Button>
          <Button onClick={handleExport} disabled={isExporting}>
            {isExporting ? (
              <Loader2 className="mr-1 h-4 w-4 animate-spin" />
            ) : null}
            {t.editor.downloadTemplatePackage}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
