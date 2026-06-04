"use client";

import { Store, Trash2 } from "@/components/ui/icons";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
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
import { Skeleton } from "@/components/ui/skeleton";
import {
  applyResolvedAuthError,
  resolveAuthError,
} from "@/core/auth/api-error";
import { useI18n } from "@/core/i18n/hooks";
import { useMarketplaceListing } from "@/core/marketplace/hooks";
import {
  useArchiveReportTemplate,
  useDeleteReportTemplate,
  usePublishReportTemplate,
  useReportTemplate,
  useReportTemplateVersion,
  useReportTemplateVersions,
  useUpdateReportTemplate,
  useValidateReportTemplate,
} from "@/core/report-templates";

interface Props {
  templateId: string;
}

export function ReportTemplateDetailPage({ templateId }: Props) {
  const router = useRouter();
  const { t } = useI18n();
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
  const canEdit = Boolean(
    template && !isPublished && template.visibility !== "builtin",
  );

  const visibilityLabel = template
    ? {
        private: t.marketplace.visibilityPrivate,
        tenant: t.marketplace.visibilityTenant,
        builtin: t.marketplace.visibilityBuiltin,
      }[template.visibility]
    : "";

  const statusLabel = template
    ? {
        draft: t.marketplace.statusDraft,
        published: t.marketplace.statusPublished,
        archived: t.marketplace.statusArchived,
      }[template.status]
    : "";

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
          ? `${t.editor.validationSuccess} (${result.warnings.length})`
          : t.editor.validationSuccess,
      );
      return;
    }
    toast.error(`${t.editor.validationFailed} (${result.errors.length})`);
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
      toast.success(t.editor.saveSuccess);
    } catch (err) {
      const authError = resolveAuthError(err, t.reportTemplates.saveDraft);
      if (authError) {
        toast.error(authError.message);
        applyResolvedAuthError(authError, window.location.pathname);
        return;
      }
      toast.error(`${t.editor.saveFailed}: ${(err as Error).message}`);
    }
  }

  async function handlePublish() {
    if (!template || !canEdit) return;
    try {
      await publish.mutateAsync({
        expected_current_version: template.current_version,
        changelog: "",
      });
      toast.success(t.editor.publishSuccess);
    } catch (err) {
      const authError = resolveAuthError(
        err,
        t.reportTemplates.publishNewVersion,
      );
      if (authError) {
        toast.error(authError.message);
        applyResolvedAuthError(authError, window.location.pathname);
        return;
      }
      toast.error(`${t.editor.publishFailed}: ${(err as Error).message}`);
    }
  }

  async function handleArchive() {
    if (!template) return;
    try {
      await archive.mutateAsync(template.etag);
      toast.success(t.reportTemplates.archiveSuccess);
    } catch (err) {
      const authError = resolveAuthError(err, t.reportTemplates.archive);
      if (authError) {
        toast.error(authError.message);
        applyResolvedAuthError(authError, window.location.pathname);
        return;
      }
      toast.error(
        `${t.reportTemplates.archiveFailed}: ${(err as Error).message}`,
      );
    }
  }

  async function handleDelete() {
    if (!template) return;
    try {
      await deleteTemplate.mutateAsync(template.etag);
      toast.success(t.reportTemplates.deleteSuccess);
      setShowDeleteDialog(false);
      router.push("/workspace/report-templates");
    } catch (err) {
      const authError = resolveAuthError(err, t.common.delete);
      if (authError) {
        toast.error(authError.message);
        applyResolvedAuthError(authError, window.location.pathname);
        return;
      }
      toast.error(
        `${t.reportTemplates.deleteFailed}: ${(err as Error).message}`,
      );
    }
  }

  if (isLoading) {
    return (
      <div className="flex h-full flex-col gap-4 p-6">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="space-y-2">
            <Skeleton className="h-4 w-20 rounded" />
            <Skeleton className="h-7 w-48 rounded" />
            <Skeleton className="h-3 w-64 rounded" />
          </div>
          <div className="flex gap-2">
            <Skeleton className="h-9 w-16 rounded" />
            <Skeleton className="h-9 w-16 rounded" />
            <Skeleton className="h-9 w-20 rounded" />
            <Skeleton className="h-9 w-14 rounded" />
          </div>
        </div>
        <div className="grid flex-1 grid-cols-[200px_1fr] gap-4 overflow-hidden">
          <Skeleton className="h-full rounded" />
          <Skeleton className="h-full rounded" />
        </div>
      </div>
    );
  }

  if (error || !template) {
    return (
      <div className="p-6">
        <Link href="/workspace/report-templates" className="text-sm underline">
          {t.reportTemplates.backToTemplates}
        </Link>
        <div className="mt-4 rounded border border-destructive bg-destructive/10 p-3 text-sm">
          {error ? String(error) : t.reportTemplates.notFound}
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
            {t.reportTemplates.backToTemplates}
          </Link>
          <h1 className="mt-1 text-2xl font-semibold">
            {template.display_name}
          </h1>
          <div className="text-muted-foreground mt-1 text-xs">
            <code className="font-mono">{template.name}</code> |{" "}
            <span>{visibilityLabel}</span> | v{template.current_version} |{" "}
            {statusLabel}
          </div>
          {marketplaceSource && (
            <div className="mt-1.5 flex items-center gap-2">
              <Badge
                variant="outline"
                className="rounded-sm border-blue-500/30 bg-blue-500/10 text-[10px] text-blue-600 hover:bg-blue-500/20"
                asChild
              >
                <Link
                  href={`/workspace/template-marketplace/${marketplaceSource.listing_id}`}
                >
                  <Store className="h-3 w-3" />
                  {t.reportTemplates.installedFromMarketplace}
                </Link>
              </Badge>
              {upstreamListing &&
                upstreamListing.template_version >
                  marketplaceSource.source_version && (
                  <Badge
                    variant="outline"
                    className="rounded-sm border-amber-500/30 bg-amber-500/10 text-[10px] text-amber-600"
                  >
                    {t.reportTemplates.updateAvailable} (
                    v{upstreamListing.template_version})
                  </Badge>
                )}
            </div>
          )}
        </div>
        <div className="flex gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={handleValidate}
            disabled={validate.isPending}
          >
            {validate.isPending
              ? t.editor.validating
              : t.reportTemplates.validateDsl}
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={handleSave}
            disabled={!canEdit || update.isPending}
          >
            {update.isPending ? t.editor.saving : t.reportTemplates.saveDraft}
          </Button>
          <Button
            size="sm"
            onClick={handlePublish}
            disabled={!canEdit || publish.isPending}
          >
            {publish.isPending
              ? t.editor.publishing
              : t.reportTemplates.publishNewVersion}
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={handleArchive}
          >
            {t.reportTemplates.archive}
          </Button>
          {isArchived && (
            <Button
              variant="destructive"
              size="sm"
              onClick={() => setShowDeleteDialog(true)}
            >
              <Trash2 />
              {t.common.delete}
            </Button>
          )}
        </div>
      </header>

      <div className="grid flex-1 grid-cols-[200px_1fr] gap-4 overflow-hidden">
        <aside className="overflow-y-auto rounded-xl bg-muted/30 p-3">
          <h2 className="mb-2 text-sm font-medium">
            {t.reportTemplates.versions}
          </h2>
          <ul className="space-y-1 text-sm">
            <li>
              <button
                type="button"
                className={`w-full rounded px-2 py-1 text-left ${selectedVersion === 0 ? "bg-accent font-medium" : "hover:bg-accent"}`}
                onClick={() => setSelectedVersion(0)}
              >
                v0 {t.reportTemplates.workingDraft}
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

        <main className="flex flex-col gap-3 overflow-hidden rounded-xl bg-muted/30 p-3">
          {parseError && (
            <div className="rounded border border-destructive bg-destructive/10 p-2 text-xs">
              {t.reportTemplates.jsonParseFailed}: {parseError}
            </div>
          )}
          {!canEdit && (
            <div className="rounded border border-amber-500/30 bg-amber-500/10 p-2 text-xs">
              {isPublished
                ? t.reportTemplates.publishedReadonly
                : t.reportTemplates.builtinReadonly}
            </div>
          )}
          <label className="text-xs font-medium text-muted-foreground">
            {t.reportTemplates.dslJson}
          </label>
          <textarea
            className="min-h-[160px] flex-1 rounded border bg-background p-3 font-mono text-xs focus:outline-none focus:ring-1 focus:ring-ring"
            value={editedJson}
            onChange={(e) => setEditedJson(e.target.value)}
            readOnly={!canEdit}
            spellCheck={false}
          />
          <label className="text-xs font-medium text-muted-foreground">
            {t.reportTemplates.dslYaml}
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
            <DialogTitle>{t.reportTemplates.deleteTemplateTitle}</DialogTitle>
            <DialogDescription>
              <strong>{template.display_name}</strong>{" "}
              {t.reportTemplates.deleteTemplateDescription}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setShowDeleteDialog(false)}
              disabled={deleteTemplate.isPending}
            >
              {t.common.cancel}
            </Button>
            <Button
              variant="destructive"
              size="sm"
              onClick={handleDelete}
              disabled={deleteTemplate.isPending}
            >
              {deleteTemplate.isPending
                ? t.reportTemplates.deleting
                : t.reportTemplates.deletePermanently}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
