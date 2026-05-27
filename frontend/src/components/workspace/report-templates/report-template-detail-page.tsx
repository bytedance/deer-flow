"use client";

import { Store, Trash2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  applyResolvedAuthError,
  resolveAuthError,
} from "@/core/auth/api-error";
import { useMarketplaceListing } from "@/core/marketplace/hooks";
import {
  useArchiveReportTemplate,
  useDeleteReportTemplate,
  usePublishReportTemplate,
  useReportTemplate,
  useReportTemplateVersions,
  useReportTemplateVersion,
  useUpdateReportTemplate,
  useValidateReportTemplate,
} from "@/core/report-templates";

interface Props {
  templateId: string;
}

export function ReportTemplateDetailPage({ templateId }: Props) {
  const router = useRouter();
  const { detail, isLoading, error } = useReportTemplate(templateId);
  const { versions } = useReportTemplateVersions(templateId);
  const template = detail?.template ?? null;

  const marketplaceSource = template?.marketplace_source;
  const { listing: upstreamListing } = useMarketplaceListing(
    marketplaceSource?.listing_id ?? "",
  );

  const [selectedVersion, setSelectedVersion] = useState<number>(0);
  const { snapshot } = useReportTemplateVersion(
    templateId,
    selectedVersion >= 0 ? selectedVersion : 0,
  );

  const [editedYaml, setEditedYaml] = useState("");
  const [editedJson, setEditedJson] = useState("");
  const [parseError, setParseError] = useState<string | null>(null);
  const [showDeleteDialog, setShowDeleteDialog] = useState(false);

  useEffect(() => {
    if (!snapshot) return;
    setEditedYaml(snapshot.dsl_yaml);
    setEditedJson(JSON.stringify(snapshot.dsl, null, 2));
    setParseError(null);
  }, [snapshot]);

  const update = useUpdateReportTemplate(templateId);
  const publish = usePublishReportTemplate(templateId);
  const validate = useValidateReportTemplate(templateId);
  const archive = useArchiveReportTemplate(templateId);
  const deleteTemplate = useDeleteReportTemplate(templateId);

  const isPublished = template?.status === "published";
  const isArchived = template?.status === "archived";
  const canEdit = template && !isPublished && template.visibility !== "builtin";

  function parseDsl(): Record<string, unknown> | null {
    try {
      const parsed = JSON.parse(editedJson) as Record<string, unknown>;
      setParseError(null);
      return parsed;
    } catch (err) {
      setParseError((err as Error).message);
      return null;
    }
  }

  async function handleValidate() {
    const dsl = parseDsl();
    if (!dsl) return;
    const result = await validate.mutateAsync(dsl);
    if (result.valid) {
      toast.success(
        result.warnings.length > 0
          ? `Validation passed with ${result.warnings.length} warning(s)`
          : "Validation passed",
      );
      return;
    }
    toast.error(`Validation failed with ${result.errors.length} error(s)`);
  }

  async function handleSave() {
    if (!template || !canEdit) return;
    const dsl = parseDsl();
    if (!dsl) return;
    try {
      await update.mutateAsync({
        dsl,
        dsl_yaml: editedYaml,
        expected_etag: template.etag,
      });
      toast.success("Draft saved");
    } catch (err) {
      const authError = resolveAuthError(err, "保存");
      if (authError) {
        toast.error(authError.message);
        applyResolvedAuthError(authError, window.location.pathname);
        return;
      }
      toast.error(`Save failed: ${(err as Error).message}`);
    }
  }

  async function handlePublish() {
    if (!template || !canEdit) return;
    try {
      await publish.mutateAsync({
        expected_current_version: template.current_version,
        changelog: "",
      });
      toast.success("New version published");
    } catch (err) {
      const authError = resolveAuthError(err, "发布");
      if (authError) {
        toast.error(authError.message);
        applyResolvedAuthError(authError, window.location.pathname);
        return;
      }
      toast.error(`Publish failed: ${(err as Error).message}`);
    }
  }

  async function handleArchive() {
    if (!template) return;
    try {
      await archive.mutateAsync(template.etag);
      toast.success("Template archived");
    } catch (err) {
      const authError = resolveAuthError(err, "归档");
      if (authError) {
        toast.error(authError.message);
        applyResolvedAuthError(authError, window.location.pathname);
        return;
      }
      toast.error(`Archive failed: ${(err as Error).message}`);
    }
  }

  async function handleDelete() {
    if (!template) return;
    try {
      await deleteTemplate.mutateAsync(template.etag);
      toast.success("Template deleted");
      setShowDeleteDialog(false);
      router.push("/workspace/report-templates");
    } catch (err) {
      const authError = resolveAuthError(err, "删除");
      if (authError) {
        toast.error(authError.message);
        applyResolvedAuthError(authError, window.location.pathname);
        return;
      }
      toast.error(`Delete failed: ${(err as Error).message}`);
    }
  }

  if (isLoading) {
    return <div className="p-6 text-sm text-muted-foreground">Loading...</div>;
  }

  if (error || !template) {
    return (
      <div className="p-6">
        <Link href="/workspace/report-templates" className="text-sm underline">
          Back to templates
        </Link>
        <div className="mt-4 rounded border border-destructive bg-destructive/10 p-3 text-sm">
          {error ? String(error) : "Template not found"}
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col gap-4 p-6">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <Link
            href="/workspace/report-templates"
            className="text-muted-foreground text-xs underline-offset-2 hover:underline"
          >
            Back to report templates
          </Link>
          <h1 className="mt-1 text-2xl font-semibold">
            {template.display_name}
          </h1>
          <div className="text-muted-foreground mt-1 text-xs">
            <code className="font-mono">{template.name}</code> |{" "}
            <span className="capitalize">{template.visibility}</span> | v
            {template.current_version} | {template.status}
          </div>
          {marketplaceSource && (
            <div className="mt-1.5 flex items-center gap-2">
              <Link
                href={`/workspace/template-marketplace/${marketplaceSource.listing_id}`}
                className="inline-flex items-center gap-1 rounded-full border border-blue-500/30 bg-blue-500/10 px-2 py-0.5 text-[10px] font-medium text-blue-600 hover:bg-blue-500/20"
              >
                <Store className="h-3 w-3" />
                Installed from marketplace
              </Link>
              {upstreamListing &&
                upstreamListing.template_version >
                  marketplaceSource.source_version && (
                  <span className="inline-flex items-center rounded-full border border-amber-500/30 bg-amber-500/10 px-2 py-0.5 text-[10px] font-medium text-amber-600">
                    Update available (v{upstreamListing.template_version})
                  </span>
                )}
            </div>
          )}
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            className="rounded border px-3 py-1.5 text-sm hover:bg-accent disabled:opacity-50"
            onClick={handleValidate}
            disabled={validate.isPending}
          >
            Validate DSL
          </button>
          <button
            type="button"
            className="rounded border px-3 py-1.5 text-sm hover:bg-accent disabled:opacity-50"
            onClick={handleSave}
            disabled={!canEdit || update.isPending}
          >
            Save draft
          </button>
          <button
            type="button"
            className="rounded bg-primary px-3 py-1.5 text-sm text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
            onClick={handlePublish}
            disabled={!canEdit || publish.isPending}
          >
            {publish.isPending ? "Publishing..." : "Publish new version"}
          </button>
          <button
            type="button"
            className="rounded border px-3 py-1.5 text-sm text-muted-foreground hover:bg-accent"
            onClick={handleArchive}
          >
            Archive
          </button>
          {isArchived && (
            <button
              type="button"
              className="rounded border border-destructive/30 px-3 py-1.5 text-sm text-destructive hover:bg-destructive/10"
              onClick={() => setShowDeleteDialog(true)}
            >
              <Trash2 className="mr-1 inline h-3.5 w-3.5" />
              Delete
            </button>
          )}
        </div>
      </header>

      <div className="grid flex-1 grid-cols-[200px_1fr] gap-4 overflow-hidden">
        <aside className="overflow-y-auto rounded border bg-card p-3">
          <h2 className="mb-2 text-sm font-medium">Versions</h2>
          <ul className="space-y-1 text-sm">
            <li>
              <button
                type="button"
                className={`w-full rounded px-2 py-1 text-left ${selectedVersion === 0 ? "bg-accent font-medium" : "hover:bg-accent"}`}
                onClick={() => setSelectedVersion(0)}
              >
                v0 Working draft
              </button>
            </li>
            {versions.map((version) => (
              <li key={version}>
                <button
                  type="button"
                  className={`w-full rounded px-2 py-1 text-left ${selectedVersion === version ? "bg-accent font-medium" : "hover:bg-accent"}`}
                  onClick={() => setSelectedVersion(version)}
                >
                  v{version}
                </button>
              </li>
            ))}
          </ul>
        </aside>

        <main className="flex flex-col gap-3 overflow-hidden rounded border bg-card p-3">
          {parseError && (
            <div className="rounded border border-destructive bg-destructive/10 p-2 text-xs">
              JSON parse failed: {parseError}
            </div>
          )}
          {!canEdit && (
            <div className="rounded border border-amber-500/30 bg-amber-500/10 p-2 text-xs">
              {isPublished
                ? "Published versions cannot be edited in place. Fork the template to continue."
                : "Builtin templates are read-only."}
            </div>
          )}
          <label className="text-xs font-medium text-muted-foreground">
            DSL (JSON)
          </label>
          <textarea
            className="min-h-[160px] flex-1 rounded border bg-background p-3 font-mono text-xs focus:outline-none focus:ring-1 focus:ring-ring"
            value={editedJson}
            onChange={(e) => setEditedJson(e.target.value)}
            readOnly={!canEdit}
            spellCheck={false}
          />
          <label className="text-xs font-medium text-muted-foreground">
            DSL YAML
          </label>
          <textarea
            className="min-h-[120px] flex-1 rounded border bg-background p-3 font-mono text-xs focus:outline-none focus:ring-1 focus:ring-ring"
            value={editedYaml}
            onChange={(e) => setEditedYaml(e.target.value)}
            readOnly={!canEdit}
            spellCheck={false}
          />
        </main>
      </div>

      <Dialog open={showDeleteDialog} onOpenChange={setShowDeleteDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete template</DialogTitle>
            <DialogDescription>
              This will permanently delete <strong>{template.display_name}</strong> and all its versions. This action cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <button
              type="button"
              className="rounded border px-3 py-1.5 text-sm hover:bg-accent"
              onClick={() => setShowDeleteDialog(false)}
              disabled={deleteTemplate.isPending}
            >
              Cancel
            </button>
            <button
              type="button"
              className="rounded bg-destructive px-3 py-1.5 text-sm text-destructive-foreground hover:bg-destructive/90 disabled:opacity-50"
              onClick={handleDelete}
              disabled={deleteTemplate.isPending}
            >
              {deleteTemplate.isPending ? "Deleting..." : "Delete permanently"}
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
