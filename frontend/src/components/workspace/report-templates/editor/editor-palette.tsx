"use client";

import {
  BarChart3,
  CreditCard,
  Database,
  FileText,
  FormInput,
  GitBranch,
  Image,
  LayoutGrid,
  Table2,
} from "lucide-react";

import { useI18n } from "@/core/i18n/hooks";

export function EditorPalette() {
  const { t } = useI18n();

  const paletteGroups = [
    {
      label: t.editor.formFieldsGroup,
      items: [
        { type: "text", label: t.editor.textInput, icon: FormInput },
        { type: "select", label: t.editor.selectInput, icon: FormInput },
        {
          type: "multi-select",
          label: t.editor.multiSelectInput,
          icon: FormInput,
        },
        { type: "date", label: t.editor.datePicker, icon: FormInput },
        {
          type: "device-selector",
          label: t.editor.deviceSelector,
          icon: FormInput,
        },
        {
          type: "device-selector-multi",
          label: t.editor.deviceMultiSelect,
          icon: FormInput,
        },
      ],
    },
    {
      label: t.editor.sectionComponentsGroup,
      items: [
        { type: "markdown", label: t.editor.markdown, icon: FileText },
        { type: "card", label: t.editor.card, icon: CreditCard },
        { type: "card_group", label: t.editor.cardGroup, icon: LayoutGrid },
        { type: "table", label: t.editor.table, icon: Table2 },
        { type: "echart", label: t.editor.chart, icon: BarChart3 },
        { type: "image", label: t.editor.image, icon: Image },
      ],
    },
    {
      label: t.editor.dataPipelineGroup,
      items: [
        { type: "data_step", label: t.editor.dataStep, icon: Database },
        { type: "transform", label: t.editor.transform, icon: GitBranch },
      ],
    },
  ];

  return (
    <div className="p-3">
      <h3 className="mb-3 text-xs font-semibold uppercase text-muted-foreground">
        {t.editor.components}
      </h3>
      {paletteGroups.map((group) => (
        <div key={group.label} className="mb-4">
          <h4 className="mb-1.5 text-xs font-medium text-muted-foreground">
            {group.label}
          </h4>
          <div className="space-y-1">
            {group.items.map((item) => {
              const Icon = item.icon;
              return (
                <div
                  key={item.type}
                  className="flex cursor-grab items-center gap-2 rounded-md border border-dashed border-transparent px-2 py-1.5 text-sm transition-colors hover:border-border hover:bg-muted/50"
                  draggable
                  onDragStart={(event) => {
                    event.dataTransfer.setData(
                      "application/template-component",
                      item.type,
                    );
                  }}
                >
                  <Icon className="h-3.5 w-3.5 text-muted-foreground" />
                  <span>{item.label}</span>
                </div>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}
