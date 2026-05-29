"use client";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useI18n } from "@/core/i18n/hooks";
import type { ReportTemplateDSL } from "@/core/report-templates/use-template-dsl";

interface EditorPropertyPanelProps {
  dsl: ReportTemplateDSL;
  onUpdate: (updater: (prev: ReportTemplateDSL) => ReportTemplateDSL) => void;
}

export function EditorPropertyPanel({
  dsl,
  onUpdate,
}: EditorPropertyPanelProps) {
  const { t } = useI18n();

  return (
    <div className="space-y-4 p-4">
      <h3 className="text-xs font-semibold uppercase text-muted-foreground">
        {t.editor.properties}
      </h3>

      <div className="space-y-3">
        <div>
          <Label className="text-xs">{t.editor.templateNameLabel}</Label>
          <Input
            value={dsl.name}
            onChange={(event) =>
              onUpdate((prev) => ({ ...prev, name: event.target.value }))
            }
            className="h-8 text-sm"
            placeholder={t.editor.templateNamePlaceholder}
          />
          <p className="mt-0.5 text-[10px] text-muted-foreground">
            {t.editor.templateNameHint}
          </p>
        </div>

        <div>
          <Label className="text-xs">{t.editor.templateDisplayNameLabel}</Label>
          <Input
            value={dsl.display_name ?? ""}
            onChange={(event) =>
              onUpdate((prev) => ({
                ...prev,
                display_name: event.target.value,
              }))
            }
            className="h-8 text-sm"
            placeholder={t.editor.templateDisplayNamePlaceholder}
          />
        </div>

        <div>
          <Label className="text-xs">{t.editor.descriptionLabel}</Label>
          <Textarea
            value={dsl.description ?? ""}
            onChange={(event) =>
              onUpdate((prev) => ({
                ...prev,
                description: event.target.value,
              }))
            }
            className="min-h-[80px] text-sm"
            placeholder={t.editor.templateDescriptionPlaceholder}
          />
        </div>
      </div>

      <div className="mt-6 rounded-lg bg-muted p-3">
        <h4 className="mb-2 text-xs font-semibold">{t.editor.structure}</h4>
        <dl className="space-y-1 text-xs">
          <div className="flex justify-between">
            <dt className="text-muted-foreground">{t.editor.formSteps}</dt>
            <dd className="font-mono">{dsl.form_steps?.length ?? 0}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-muted-foreground">{t.editor.dataSteps}</dt>
            <dd className="font-mono">{dsl.data_steps?.length ?? 0}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-muted-foreground">{t.editor.transforms}</dt>
            <dd className="font-mono">{dsl.transforms?.length ?? 0}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-muted-foreground">{t.editor.sections}</dt>
            <dd className="font-mono">{dsl.sections?.length ?? 0}</dd>
          </div>
        </dl>
      </div>

      <div className="space-y-2">
        <Label className="text-xs">{t.editor.exportFormats}</Label>
        <Input
          value={dsl.export?.formats?.join(", ") ?? "md"}
          onChange={(event) => {
            const formats = event.target.value
              .split(",")
              .map((value) => value.trim())
              .filter(Boolean);

            onUpdate((prev) => ({
              ...prev,
              export: { ...prev.export, formats },
            }));
          }}
          className="h-8 text-sm"
          placeholder={t.editor.exportFormatsPlaceholder}
        />
        <p className="text-[10px] text-muted-foreground">
          {t.editor.exportFormatsHint}
        </p>
      </div>
    </div>
  );
}
