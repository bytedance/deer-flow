"use client";

import {
  ArrowLeft,
  Code,
  Eye,
  FileDown,
  Loader2,
  Save,
  Send,
  ShoppingBag,
} from "lucide-react";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";
import {
  applyResolvedAuthError,
  resolveAuthError,
} from "@/core/auth/api-error";
import { useI18n } from "@/core/i18n/hooks";
import {
  publishReportTemplate,
  updateReportTemplate,
} from "@/core/report-templates/api";
import { useReportTemplate, useReportTemplateVersion } from "@/core/report-templates/hooks";
import {
  type ReportTemplateDSL,
  useTemplateDSL,
} from "@/core/report-templates/use-template-dsl";

import { DataStepsPanel } from "./data-steps-panel";
import { EditorActionsDialog } from "./editor-actions-dialog";
import { EditorPalette } from "./editor-palette";
import { EditorPropertyPanel } from "./editor-property-panel";
import { FormStepsPanel } from "./form-steps-panel";
import { SectionsPanel } from "./sections-panel";
import { ValidationPanel } from "./validation-panel";
import { YamlEditor } from "./yaml-editor";

export function TemplateEditorPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const { t } = useI18n();
  const templateId = params.id;

  const { detail, isLoading } = useReportTemplate(templateId);
  const { snapshot } = useReportTemplateVersion(
    detail?.template.id ?? null,
    detail?.template.current_version ?? null,
  );

  const [activeTab, setActiveTab] = useState<"form" | "data" | "sections">("form");
  const [showYaml, setShowYaml] = useState(false);
  const [selectedItem, setSelectedItem] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [isPublishing, setIsPublishing] = useState(false);
  const [showPublishDialog, setShowPublishDialog] = useState(false);
  const [showExportDialog, setShowExportDialog] = useState(false);

  const initialDSL = useMemo<ReportTemplateDSL | undefined>(() => {
    if (snapshot?.dsl) {
      return snapshot.dsl as unknown as ReportTemplateDSL;
    }
    return undefined;
  }, [snapshot]);

  const dslHook = useTemplateDSL(initialDSL);

  useEffect(() => {
    if (!dslHook.isDirty) return;

    const handler = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };

    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [dslHook.isDirty]);

  const handleSave = useCallback(async () => {
    if (!detail?.template) return;

    setIsSaving(true);
    try {
      await updateReportTemplate(templateId, {
        dsl: dslHook.dsl as unknown as Record<string, unknown>,
        dsl_yaml: dslHook.dslYaml,
        expected_etag: detail.template.etag,
      });
      dslHook.markClean();
      toast.success(t.editor.saveSuccess);
    } catch (err) {
      const authError = resolveAuthError(err, t.editor.save);
      if (authError) {
        toast.error(authError.message);
        applyResolvedAuthError(authError, window.location.pathname);
        return;
      }
      toast.error((err as Error).message || t.editor.saveFailed);
    } finally {
      setIsSaving(false);
    }
  }, [detail, dslHook, t.editor.save, t.editor.saveFailed, t.editor.saveSuccess, templateId]);

  const handlePublish = useCallback(async () => {
    if (!detail?.template) return;

    setIsPublishing(true);
    try {
      await updateReportTemplate(templateId, {
        dsl: dslHook.dsl as unknown as Record<string, unknown>,
        dsl_yaml: dslHook.dslYaml,
        expected_etag: detail.template.etag,
      });
      dslHook.markClean();

      await publishReportTemplate(templateId, {
        expected_current_version: detail.template.current_version,
      });
      toast.success(t.editor.publishSuccess);
    } catch (err) {
      const authError = resolveAuthError(err, t.editor.publish);
      if (authError) {
        toast.error(authError.message);
        applyResolvedAuthError(authError, window.location.pathname);
        return;
      }
      toast.error((err as Error).message || t.editor.publishFailed);
    } finally {
      setIsPublishing(false);
    }
  }, [
    detail,
    dslHook,
    t.editor.publish,
    t.editor.publishFailed,
    t.editor.publishSuccess,
    templateId,
  ]);

  if (isLoading || !detail) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center justify-between border-b px-4 py-2">
        <div className="flex items-center gap-3">
          <Button
            variant="ghost"
            size="icon"
            onClick={() => router.push("/workspace/report-templates")}
          >
            <ArrowLeft className="h-4 w-4" />
          </Button>
          <div>
            <h1 className="text-sm font-semibold">
              {detail.template.display_name || t.editor.templateEditorFallbackTitle}
            </h1>
            <p className="text-xs text-muted-foreground">
              {dslHook.isDirty ? t.editor.unsavedChanges : t.editor.allSaved}
              {detail.template.status === "published" &&
                ` | v${detail.template.current_version}`}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setShowYaml((prev) => !prev)}
          >
            {showYaml ? (
              <Eye className="mr-1 h-4 w-4" />
            ) : (
              <Code className="mr-1 h-4 w-4" />
            )}
            {showYaml ? t.editor.preview : t.editor.yaml}
          </Button>

          <Button
            variant="outline"
            size="sm"
            onClick={handleSave}
            disabled={isSaving || !dslHook.isDirty}
          >
            {isSaving ? (
              <Loader2 className="mr-1 h-4 w-4 animate-spin" />
            ) : (
              <Save className="mr-1 h-4 w-4" />
            )}
            {t.editor.save}
          </Button>

          <Button
            variant="outline"
            size="sm"
            onClick={() => setShowExportDialog(true)}
          >
            <FileDown className="mr-1 h-4 w-4" />
            {t.editor.export}
          </Button>

          <Button size="sm" onClick={handlePublish} disabled={isPublishing}>
            {isPublishing ? (
              <Loader2 className="mr-1 h-4 w-4 animate-spin" />
            ) : (
              <Send className="mr-1 h-4 w-4" />
            )}
            {t.editor.publish}
          </Button>

          <Button
            variant="secondary"
            size="sm"
            onClick={() => setShowPublishDialog(true)}
          >
            <ShoppingBag className="mr-1 h-4 w-4" />
            {t.editor.marketplace}
          </Button>
        </div>
      </header>

      <div className="flex flex-1 overflow-hidden">
        <div className="w-56 shrink-0 overflow-y-auto border-r">
          <EditorPalette />
        </div>

        <div className="flex flex-1 flex-col overflow-hidden">
          <Tabs
            value={activeTab}
            onValueChange={(value) => setActiveTab(value as typeof activeTab)}
            className="flex flex-1 flex-col"
          >
            <div className="border-b px-4">
              <TabsList variant="line">
                <TabsTrigger value="form">
                  {t.editor.formSteps} ({dslHook.dsl.form_steps?.length ?? 0})
                </TabsTrigger>
                <TabsTrigger value="data">
                  {t.editor.dataSteps} ({dslHook.dsl.data_steps?.length ?? 0})
                </TabsTrigger>
                <TabsTrigger value="sections">
                  {t.editor.sections} ({dslHook.dsl.sections?.length ?? 0})
                </TabsTrigger>
              </TabsList>
            </div>

            <TabsContent value="form" className="flex-1 overflow-y-auto p-4">
              <FormStepsPanel
                steps={dslHook.dsl.form_steps ?? []}
                onUpdate={dslHook.updateFormSteps}
                selectedId={selectedItem}
                onSelect={setSelectedItem}
              />
            </TabsContent>

            <TabsContent value="data" className="flex-1 overflow-y-auto p-4">
              <DataStepsPanel
                dataSteps={dslHook.dsl.data_steps ?? []}
                transforms={dslHook.dsl.transforms ?? []}
                onUpdateDataSteps={dslHook.updateDataSteps}
                onUpdateTransforms={dslHook.updateTransforms}
                selectedId={selectedItem}
                onSelect={setSelectedItem}
              />
            </TabsContent>

            <TabsContent value="sections" className="flex-1 overflow-y-auto p-4">
              <SectionsPanel
                sections={dslHook.dsl.sections ?? []}
                onUpdate={dslHook.updateSections}
                selectedId={selectedItem}
                onSelect={setSelectedItem}
                availableSources={[]}
              />
            </TabsContent>
          </Tabs>

          {showYaml && (
            <div className="border-t" style={{ height: "40%" }}>
              <YamlEditor
                value={dslHook.dslYaml}
                onChange={dslHook.loadFromYaml}
              />
            </div>
          )}

          <ValidationPanel templateId={templateId} dsl={dslHook.dsl} />
        </div>

        <div className="w-72 shrink-0 overflow-y-auto border-l">
          <EditorPropertyPanel dsl={dslHook.dsl} onUpdate={dslHook.updateDSL} />
        </div>
      </div>

      {showPublishDialog && (
        <EditorActionsDialog
          open={showPublishDialog}
          onOpenChange={setShowPublishDialog}
          templateId={templateId}
          mode="publish"
        />
      )}
      {showExportDialog && (
        <EditorActionsDialog
          open={showExportDialog}
          onOpenChange={setShowExportDialog}
          templateId={templateId}
          mode="export"
        />
      )}
    </div>
  );
}
