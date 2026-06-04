"use client";

import {
  ArrowLeft,
  FileText,
  Loader2,
  ClipboardList,
  Wrench,
  TrendingUp,
  Activity,
  CalendarDays,
  Package,
} from "@/components/ui/icons";
import { useRouter } from "next/navigation";
import { useState, useCallback } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
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
import type { BlueprintSummary } from "@/core/blueprints/api";
import {
  useBlueprints,
  useCreateTemplateFromBlueprint,
} from "@/core/blueprints/hooks";
import { useI18n } from "@/core/i18n/hooks";

const CATEGORY_ICONS: Record<string, typeof FileText> = {
  daily: CalendarDays,
  weekly: CalendarDays,
  monthly: CalendarDays,
  trend: TrendingUp,
  diagnosis: Wrench,
  failure: Activity,
  closure: ClipboardList,
  inspection: Package,
};

export function BlueprintCatalogPage() {
  const router = useRouter();
  const { t } = useI18n();
  const { blueprints, isLoading } = useBlueprints();
  const [selectedBlueprint, setSelectedBlueprint] =
    useState<BlueprintSummary | null>(null);
  const [templateName, setTemplateName] = useState("");

  const createMutation = useCreateTemplateFromBlueprint(
    selectedBlueprint?.id ?? "",
  );

  const handleCreate = useCallback(async () => {
    if (!selectedBlueprint || !templateName.trim()) return;
    try {
      const result = await createMutation.mutateAsync({
        name: templateName.toLowerCase().replace(/\s+/g, "-"),
        visibility: "private",
      });
      toast.success(t.editor.templateCreated);
      router.push(`/workspace/report-templates/editor/${result.template_id}`);
    } catch (err) {
      toast.error((err as Error).message || t.editor.createFailed);
    }
  }, [selectedBlueprint, templateName, createMutation, router, t]);

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <header className="flex items-center gap-3 border-b px-6 py-4">
        <Button
          variant="ghost"
          size="icon"
          onClick={() => router.push("/workspace/report-templates")}
        >
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <div>
          <h1 className="text-lg font-semibold">{t.editor.createFromBlueprint}</h1>
          <p className="text-sm text-muted-foreground">
            {t.editor.chooseBlueprint}
          </p>
        </div>
      </header>

      {/* Blueprint grid */}
      <div className="flex-1 overflow-y-auto p-6">
        {isLoading ? (
          <div className="flex items-center justify-center py-20 text-muted-foreground">
            <Loader2 className="mr-2 h-5 w-5 animate-spin" />
            {t.editor.loadingBlueprints}
          </div>
        ) : blueprints.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20 text-muted-foreground">
            <p className="text-sm">{t.editor.noBlueprints}</p>
          </div>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {blueprints.map((bp) => (
              <BlueprintCard
                key={bp.id}
                blueprint={bp}
                onUse={() => {
                  setSelectedBlueprint(bp);
                  setTemplateName("");
                }}
              />
            ))}
          </div>
        )}
      </div>

      {/* Create dialog */}
      <Dialog
        open={!!selectedBlueprint}
        onOpenChange={(open) => {
          if (!open) setSelectedBlueprint(null);
        }}
      >
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>
              {t.editor.createFrom} {selectedBlueprint?.name}
            </DialogTitle>
            <DialogDescription>
              {selectedBlueprint?.description}
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-3">
            <div>
              <Label>{t.editor.blueprintTemplateNameLabel}</Label>
              <Input
                value={templateName}
                onChange={(e) => setTemplateName(e.target.value)}
                placeholder={t.editor.blueprintTemplateNamePlaceholder}
                autoFocus
              />
              <p className="mt-1 text-[10px] text-muted-foreground">
                {t.editor.blueprintTemplateNameHint}
              </p>
            </div>
          </div>

          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setSelectedBlueprint(null)}
            >
              {t.common.cancel}
            </Button>
            <Button
              onClick={handleCreate}
              disabled={!templateName.trim() || createMutation.isPending}
            >
              {createMutation.isPending ? (
                <Loader2 className="mr-1 h-4 w-4 animate-spin" />
              ) : null}
              {t.marketplace.createTemplate}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function BlueprintCard({
  blueprint,
  onUse,
}: {
  blueprint: BlueprintSummary;
  onUse: () => void;
}) {
  const { t } = useI18n();
  const Icon = CATEGORY_ICONS[blueprint.category] ?? FileText;

  return (
    <Card className="flex flex-col">
      <CardHeader className="pb-2">
        <div className="flex items-start gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-muted">
            <Icon className="h-5 w-5 text-muted-foreground" />
          </div>
          <div className="flex-1">
            <h3 className="text-sm font-semibold">{blueprint.name}</h3>
            <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
              {blueprint.category}
            </span>
          </div>
        </div>
      </CardHeader>
      <CardContent className="flex flex-1 flex-col">
        <p className="mb-3 flex-1 text-xs text-muted-foreground">
          {blueprint.description}
        </p>

        {blueprint.tags.length > 0 && (
          <div className="mb-3 flex flex-wrap gap-1">
            {blueprint.tags.slice(0, 3).map((tag, i) => (
              <span
                key={`${tag}-${i}`}
                className="rounded border px-1.5 py-0.5 text-[10px] text-muted-foreground"
              >
                {tag}
              </span>
            ))}
          </div>
        )}

        <Button variant="outline" size="sm" onClick={onUse}>
          {t.editor.useBlueprint}
        </Button>
      </CardContent>
    </Card>
  );
}
