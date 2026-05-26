"use client";

import {
  FileText,
  FormInput,
  LayoutGrid,
  Table2,
  BarChart3,
  Image,
  CreditCard,
  Database,
  GitBranch,
} from "lucide-react";

const PALETTE_GROUPS = [
  {
    label: "Form Fields",
    items: [
      { type: "text", label: "Text Input", icon: FormInput },
      { type: "select", label: "Select", icon: FormInput },
      { type: "multi-select", label: "Multi-Select", icon: FormInput },
      { type: "date", label: "Date Picker", icon: FormInput },
      { type: "device-selector", label: "Device Selector", icon: FormInput },
      { type: "device-selector-multi", label: "Device Multi-Select", icon: FormInput },
    ],
  },
  {
    label: "Section Components",
    items: [
      { type: "markdown", label: "Markdown", icon: FileText },
      { type: "card", label: "Card", icon: CreditCard },
      { type: "card_group", label: "Card Group", icon: LayoutGrid },
      { type: "table", label: "Table", icon: Table2 },
      { type: "echart", label: "Chart", icon: BarChart3 },
      { type: "image", label: "Image", icon: Image },
    ],
  },
  {
    label: "Data Pipeline",
    items: [
      { type: "data_step", label: "Data Step", icon: Database },
      { type: "transform", label: "Transform", icon: GitBranch },
    ],
  },
];

export function EditorPalette() {
  return (
    <div className="p-3">
      <h3 className="mb-3 text-xs font-semibold uppercase text-muted-foreground">
        Components
      </h3>
      {PALETTE_GROUPS.map((group) => (
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
                  onDragStart={(e) => {
                    e.dataTransfer.setData("application/template-component", item.type);
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
