"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { toast } from "sonner";
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

import { useReportTemplate, useReportTemplateVersion } from "@/core/report-templates/hooks";
import {
  updateReportTemplate,
  publishReportTemplate,
} from "@/core/report-templates/api";
import {
  useTemplateDSL,
  type ReportTemplateDSL,
} from "@/core/report-templates/use-template-dsl";
import { Button } from "@/components/ui/button";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";

import { EditorPalette } from "./editor-palette";
import { FormStepsPanel } from "./form-steps-panel";
import { SectionsPanel } from "./sections-panel";
import { DataStepsPanel } from "./data-steps-panel";
import { EditorPropertyPanel } from "./editor-property-panel";
import { YamlEditor } from "./yaml-editor";
import { ValidationPanel } from "./validation-panel";
import { EditorActionsDialog } from "./editor-actions-dialog";

export function TemplateEditorPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
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

  // Unsaved changes warning
  useEffect(() => {
    if (!dslHook.isDirty) return;

    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
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
      toast.success("Template saved");
    } catch (err) {
      toast.error((err as Error).message || "Failed to save");
    } finally {
      setIsSaving(false);
    }
  }, [detail, templateId, dslHook]);

  const handlePublish = useCallback(async () => {
    if (!detail?.template) return;
    setIsPublishing(true);
    try {
      // Save first
      await updateReportTemplate(templateId, {
        dsl: dslHook.dsl as unknown as Record<string, unknown>,
        dsl_yaml: dslHook.dslYaml,
        expected_etag: detail.template.etag,
      });
      dslHook.markClean();

      await publishReportTemplate(templateId, {
        expected_current_version: detail.template.current_version,
      });
      toast.success("Template published");
    } catch (err) {
      toast.error((err as Error).message || "Failed to publish");
    } finally {
      setIsPublishing(false);
    }
  }, [detail, templateId, dslHook]);

  if (isLoading || !detail) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
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
              {detail.template.display_name || "Template Editor"}
            </h1>
            <p className="text-xs text-muted-foreground">
              {dslHook.isDirty ? "Unsaved changes" : "All changes saved"}
              {detail.template.status === "published" && ` · v${detail.template.current_version}`}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setShowYaml(!showYaml)}
          >
            {showYaml ? <Eye className="mr-1 h-4 w-4" /> : <Code className="mr-1 h-4 w-4" />}
            {showYaml ? "Preview" : "YAML"}
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
            Save
          </Button>

          <Button
            variant="outline"
            size="sm"
            onClick={() => setShowExportDialog(true)}
          >
            <FileDown className="mr-1 h-4 w-4" />
            Export
          </Button>

          <Button
            size="sm"
            onClick={handlePublish}
            disabled={isPublishing}
          >
            {isPublishing ? (
              <Loader2 className="mr-1 h-4 w-4 animate-spin" />
            ) : (
              <Send className="mr-1 h-4 w-4" />
            )}
            Publish
          </Button>

          <Button
            variant="secondary"
            size="sm"
            onClick={() => setShowPublishDialog(true)}
          >
            <ShoppingBag className="mr-1 h-4 w-4" />
            Marketplace
          </Button>
        </div>
      </header>

      {/* Main editor area */}
      <div className="flex flex-1 overflow-hidden">
        {/* Left: Palette */}
        <div className="w-56 shrink-0 border-r overflow-y-auto">
          <EditorPalette />
        </div>

        {/* Center: Canvas */}
        <div className="flex flex-1 flex-col overflow-hidden">
          <Tabs
            value={activeTab}
            onValueChange={(v) => setActiveTab(v as typeof activeTab)}
            className="flex flex-1 flex-col"
          >
            <div className="border-b px-4">
              <TabsList variant="line">
                <TabsTrigger value="form">
                  Form Steps ({dslHook.dsl.form_steps?.length ?? 0})
                </TabsTrigger>
                <TabsTrigger value="data">
                  Data Steps ({dslHook.dsl.data_steps?.length ?? 0})
                </TabsTrigger>
                <TabsTrigger value="sections">
                  Sections ({dslHook.dsl.sections?.length ?? 0})
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

          {/* YAML view */}
          {showYaml && (
            <div className="border-t" style={{ height: "40%" }}>
              <YamlEditor
                value={dslHook.dslYaml}
                onChange={dslHook.loadFromYaml}
              />
            </div>
          )}

          {/* Validation */}
          <ValidationPanel templateId={templateId} dsl={dslHook.dsl} />
        </div>

        {/* Right: Property panel */}
        <div className="w-72 shrink-0 border-l overflow-y-auto">
          <EditorPropertyPanel
            dsl={dslHook.dsl}
            onUpdate={dslHook.updateDSL}
          />
        </div>
      </div>

      {/* Dialogs */}
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
