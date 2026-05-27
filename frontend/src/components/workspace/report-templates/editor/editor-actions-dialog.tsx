"use client";

import { useState, useCallback } from "react";
import { toast } from "sonner";
import { Loader2 } from "lucide-react";

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
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

import {
  applyResolvedAuthError,
  resolveAuthError,
} from "@/core/auth/api-error";
import { publishToMarketplace, exportTemplatePackage } from "@/core/marketplace/api";

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
  const [displayName, setDisplayName] = useState("");
  const [description, setDescription] = useState("");
  const [visibility, setVisibility] = useState("tenant");
  const [category, setCategory] = useState("");
  const [tags, setTags] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSubmit = useCallback(async () => {
    if (!displayName.trim()) {
      toast.error("Display name is required");
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
          .map((t) => t.trim())
          .filter(Boolean),
      });
      toast.success(result.message || "Published to marketplace");
      onOpenChange(false);
    } catch (err) {
      const authError = resolveAuthError(err, "发布");
      if (authError) {
        toast.error(authError.message);
        applyResolvedAuthError(authError, window.location.pathname);
        return;
      }
      toast.error((err as Error).message || "Failed to publish");
    } finally {
      setIsSubmitting(false);
    }
  }, [templateId, displayName, description, visibility, category, tags, onOpenChange]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Publish to Marketplace</DialogTitle>
          <DialogDescription>
            Share this template with others through the template marketplace.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div>
            <Label>Display Name *</Label>
            <Input
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              placeholder="Equipment Daily Report"
            />
          </div>

          <div>
            <Label>Description</Label>
            <Textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Describe what this template does..."
              rows={3}
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label>Visibility</Label>
              <Select value={visibility} onValueChange={setVisibility}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="tenant">Tenant</SelectItem>
                  <SelectItem value="builtin">Builtin</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label>Category</Label>
              <Input
                value={category}
                onChange={(e) => setCategory(e.target.value)}
                placeholder="daily"
              />
            </div>
          </div>

          <div>
            <Label>Tags</Label>
            <Input
              value={tags}
              onChange={(e) => setTags(e.target.value)}
              placeholder="equipment, daily, monitoring"
            />
            <p className="mt-0.5 text-[10px] text-muted-foreground">
              Comma-separated
            </p>
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={handleSubmit} disabled={isSubmitting}>
            {isSubmitting ? (
              <Loader2 className="mr-1 h-4 w-4 animate-spin" />
            ) : null}
            Publish
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
  const [isExporting, setIsExporting] = useState(false);

  const handleExport = useCallback(async () => {
    setIsExporting(true);
    try {
      const blob = await exportTemplatePackage(templateId);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${templateId}.template`;
      a.click();
      URL.revokeObjectURL(url);
      toast.success("Template exported");
      onOpenChange(false);
    } catch (err) {
      const authError = resolveAuthError(err, "导出");
      if (authError) {
        toast.error(authError.message);
        applyResolvedAuthError(authError, window.location.pathname);
        return;
      }
      toast.error((err as Error).message || "Failed to export");
    } finally {
      setIsExporting(false);
    }
  }, [templateId, onOpenChange]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-sm">
        <DialogHeader>
          <DialogTitle>Export Template</DialogTitle>
          <DialogDescription>
            Download this template as a .template file that can be imported
            into another workspace.
          </DialogDescription>
        </DialogHeader>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={handleExport} disabled={isExporting}>
            {isExporting ? (
              <Loader2 className="mr-1 h-4 w-4 animate-spin" />
            ) : null}
            Download .template
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
