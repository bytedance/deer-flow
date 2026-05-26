"use client";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

import type { ReportTemplateDSL } from "@/core/report-templates/use-template-dsl";

interface EditorPropertyPanelProps {
  dsl: ReportTemplateDSL;
  onUpdate: (updater: (prev: ReportTemplateDSL) => ReportTemplateDSL) => void;
}

export function EditorPropertyPanel({ dsl, onUpdate }: EditorPropertyPanelProps) {
  return (
    <div className="space-y-4 p-4">
      <h3 className="text-xs font-semibold uppercase text-muted-foreground">
        Template Properties
      </h3>

      <div className="space-y-3">
        <div>
          <Label className="text-xs">Name</Label>
          <Input
            value={dsl.name}
            onChange={(e) =>
              onUpdate((prev) => ({ ...prev, name: e.target.value }))
            }
            className="h-8 text-sm"
            placeholder="template-name"
          />
          <p className="mt-0.5 text-[10px] text-muted-foreground">
            kebab-case identifier
          </p>
        </div>

        <div>
          <Label className="text-xs">Display Name</Label>
          <Input
            value={dsl.display_name ?? ""}
            onChange={(e) =>
              onUpdate((prev) => ({ ...prev, display_name: e.target.value }))
            }
            className="h-8 text-sm"
            placeholder="Human Readable Name"
          />
        </div>

        <div>
          <Label className="text-xs">Description</Label>
          <Textarea
            value={dsl.description ?? ""}
            onChange={(e) =>
              onUpdate((prev) => ({ ...prev, description: e.target.value }))
            }
            className="min-h-[80px] text-sm"
            placeholder="Brief description of the template..."
          />
        </div>
      </div>

      {/* Summary stats */}
      <div className="mt-6 rounded-lg bg-muted p-3">
        <h4 className="mb-2 text-xs font-semibold">Structure</h4>
        <dl className="space-y-1 text-xs">
          <div className="flex justify-between">
            <dt className="text-muted-foreground">Form Steps</dt>
            <dd className="font-mono">{dsl.form_steps?.length ?? 0}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-muted-foreground">Data Steps</dt>
            <dd className="font-mono">{dsl.data_steps?.length ?? 0}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-muted-foreground">Transforms</dt>
            <dd className="font-mono">{dsl.transforms?.length ?? 0}</dd>
          </div>
          <div className="flex justify-between">
            <dt className="text-muted-foreground">Sections</dt>
            <dd className="font-mono">{dsl.sections?.length ?? 0}</dd>
          </div>
        </dl>
      </div>

      {/* Export config */}
      <div className="space-y-2">
        <Label className="text-xs">Export Formats</Label>
        <Input
          value={dsl.export?.formats?.join(", ") ?? "md"}
          onChange={(e) => {
            const formats = e.target.value
              .split(",")
              .map((s) => s.trim())
              .filter(Boolean);
            onUpdate((prev) => ({
              ...prev,
              export: { ...prev.export, formats },
            }));
          }}
          className="h-8 text-sm"
          placeholder="md, pdf"
        />
        <p className="text-[10px] text-muted-foreground">
          Comma-separated: md, pdf
        </p>
      </div>
    </div>
  );
}
