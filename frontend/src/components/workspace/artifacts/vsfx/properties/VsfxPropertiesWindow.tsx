"use client";

import { useMemo } from "react";

import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";

import { useVsfxContext, type VsfxHandle } from "../context";
import { VsfxFloatingWindow } from "../VsfxFloatingWindow";

type PropertyRow = {
  label: string;
  value: string;
};

type PropertyGroup = {
  name: string;
  rows: PropertyRow[];
};

type PanelContent =
  | { kind: "loading" }
  | { kind: "empty"; message: string }
  | { kind: "error"; message: string }
  | {
    groups: PropertyGroup[];
    handleLabel: string;
    kind: "ready";
  };

type VsfxPropertiesWindowProps = {
  containerElement: HTMLDivElement | null;
  minimized: boolean;
  offset: { x: number; y: number };
  onOffsetChange: (offset: { x: number; y: number }) => void;
  onToggleMinimized: () => void;
};

export function VsfxPropertiesWindow({
  containerElement,
  minimized,
  offset,
  onOffsetChange,
  onToggleMinimized,
}: VsfxPropertiesWindowProps) {
  const { state } = useVsfxContext();

  const content = useMemo<PanelContent>(() => {
    if (state.propertiesLoading) {
      return { kind: "loading" };
    }

    if (state.primaryHandle == null) {
      return {
        kind: "empty",
        message: "Select a part to inspect its properties.",
      };
    }

    if (state.propertiesError) {
      return {
        kind: "error",
        message: state.propertiesError.message || "Unable to display properties for the selected part.",
      };
    }

    if (state.properties == null) {
      return {
        kind: "empty",
        message: "No properties are available for the selected part.",
      };
    }

    try {
      const selectedProperties = resolveSelectedProperties(state.properties, state.primaryHandle);

      if (!selectedProperties) {
        return {
          kind: "empty",
          message: "No properties are available for the selected part.",
        };
      }

      if (!isPlainObject(selectedProperties)) {
        return {
          kind: "error",
          message: "Unable to display properties for the selected part.",
        };
      }

      const groups = createPropertyGroups(selectedProperties);

      if (groups.length === 0) {
        return {
          kind: "empty",
          message: "No properties are available for the selected part.",
        };
      }

      return {
        groups,
        handleLabel: formatHandleLabel(state.primaryHandle),
        kind: "ready",
      };
    }
    catch {
      return {
        kind: "error",
        message: "Unable to display properties for the selected part.",
      };
    }
  }, [state.primaryHandle, state.properties, state.propertiesError, state.propertiesLoading]);

  return (
    <VsfxFloatingWindow
      className="w-80 max-w-full"
      containerElement={containerElement}
      contentClassName="min-h-0 flex-1"
      data-testid="vsfx-properties-window"
      description={content.kind === "ready"
        ? content.handleLabel
        : "Selected part details stay scoped to this panel."}
      minimized={minimized}
      offset={offset}
      onOffsetChange={onOffsetChange}
      onToggleMinimized={onToggleMinimized}
      title="Selected properties"
    >
      {content.kind === "ready" ? (
        <ScrollArea
          className="min-h-0 flex-1"
          data-testid="vsfx-properties-scroll-region"
        >
          <div className="flex flex-col gap-4 px-4 py-4">
            {content.groups.map((group) => (
              <section className="flex flex-col gap-2" key={group.name}>
                <h3 className="text-foreground text-xs font-semibold tracking-wide uppercase">
                  {group.name}
                </h3>
                <div className="divide-border overflow-hidden rounded-md border">
                  {group.rows.map((row) => (
                     <div
                       className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)] gap-3 border-b px-3 py-2 last:border-b-0"
                       data-testid={createVsfxPropertyRowTestId(group.name, row.label)}
                       key={`${group.name}-${row.label}`}
                     >
                       <div className="text-foreground min-w-0 break-words text-sm font-medium">
                         {row.label}
                      </div>
                      <div className="text-muted-foreground min-w-0 break-words text-sm text-right">
                        {row.value}
                      </div>
                    </div>
                  ))}
                </div>
              </section>
            ))}
          </div>
        </ScrollArea>
      ) : (
        <div className="flex min-h-0 flex-1 items-center justify-center px-5 py-6 text-center">
          <div
            className={cn(
              "text-sm leading-6",
              content.kind === "error" ? "text-destructive" : "text-muted-foreground",
            )}
            role={content.kind === "error" ? "alert" : undefined}
          >
            {content.kind === "loading"
              ? "Loading selected properties…"
              : content.message}
          </div>
        </div>
      )}
    </VsfxFloatingWindow>
  );
}

function createVsfxPropertyRowTestId(groupName: string, label: string) {
  return `vsfx-property-row-${toStableSelectorPart(groupName)}-${toStableSelectorPart(label)}`;
}

function createPropertyGroups(properties: Record<string, unknown>): PropertyGroup[] {
  const generalRows: PropertyRow[] = [];
  const groups: PropertyGroup[] = [];

  for (const [key, value] of Object.entries(properties)) {
    if (value == null) {
      generalRows.push({ label: key, value: "—" });
      continue;
    }

    if (isPlainObject(value)) {
      const rows = flattenObjectEntries(value, key);

      if (rows.length > 0) {
        groups.push({ name: key, rows });
      }
      continue;
    }

    generalRows.push({ label: key, value: stringifyPropertyValue(value) });
  }

  return generalRows.length > 0
    ? [{ name: "General", rows: generalRows }, ...groups]
    : groups;
}

function flattenObjectEntries(
  value: Record<string, unknown>,
  groupName: string,
  path: string[] = [],
): PropertyRow[] {
  const rows: PropertyRow[] = [];

  for (const [key, entry] of Object.entries(value)) {
    const normalizedKey = stripGroupPrefix(key, groupName);
    const nextPath = [...path, normalizedKey];

    if (entry != null && isPlainObject(entry)) {
      rows.push(...flattenObjectEntries(entry, groupName, nextPath));
      continue;
    }

    rows.push({
      label: nextPath.join("."),
      value: stringifyPropertyValue(entry),
    });
  }

  return rows;
}

function formatHandleLabel(handle: VsfxHandle) {
  return `Handle ${String(handle)}`;
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function resolveSelectedProperties(properties: unknown, handle: VsfxHandle) {
  if (Array.isArray(properties)) {
    const selectedPart = properties.find((part) => {
      if (!isPlainObject(part)) {
        return false;
      }

      return part.handle === handle || String(part.handle) === String(handle);
    });

    return isPlainObject(selectedPart) ? selectedPart : null;
  }

  if (!isPlainObject(properties)) {
    throw new Error("Malformed properties payload");
  }

  const byHandle = properties.byHandle;

  if (byHandle !== undefined) {
    if (!isPlainObject(byHandle)) {
      throw new Error("Malformed byHandle payload");
    }

    return byHandle[String(handle)] ?? byHandle[Number(handle)] ?? byHandle[handle];
  }

  const parts = properties.parts;

  if (parts !== undefined) {
    if (!Array.isArray(parts)) {
      throw new Error("Malformed parts payload");
    }

    const selectedPart = parts.find((part) => {
      if (!isPlainObject(part)) {
        return false;
      }

      return part.handle === handle || String(part.handle) === String(handle);
    });

    if (!selectedPart || !isPlainObject(selectedPart)) {
      return null;
    }

    return isPlainObject(selectedPart.properties) ? selectedPart.properties : selectedPart;
  }

  if (Object.keys(properties).length === 0) {
    return null;
  }

  return properties;
}

function stringifyPropertyValue(value: unknown) {
  if (value == null) {
    return "—";
  }

  if (typeof value === "string") {
    return value;
  }

  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }

  if (Array.isArray(value)) {
    return value.map((item) => stringifyPropertyValue(item)).join(", ");
  }

  return JSON.stringify(value);
}

function stripGroupPrefix(key: string, groupName: string) {
  return key.startsWith(`${groupName}.`) ? key.slice(groupName.length + 1) : key;
}

function toStableSelectorPart(value: string) {
  return value.trim().toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
}
