"use client";

import { useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { ButtonGroup } from "@/components/ui/button-group";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { cn } from "@/lib/utils";

import { useVsfxContext } from "./context";
import { VSFX_TOOLBAR_GROUPS } from "./vsfx-toolbar-config";

export function VsfxToolbar({ className }: { className?: string }) {
  const context = useVsfxContext();
  const [activeDragger, setActiveDragger] = useState("orbit-pan");

  const hasSelection = context.state.selectedHandles.length > 0;
  const hasViewer = context.state.viewer !== null;
  const groups = useMemo(() => VSFX_TOOLBAR_GROUPS, []);

  return (
    <div
      className={cn(
        "bg-background/95 supports-[backdrop-filter]:bg-background/85 flex w-full flex-wrap items-center gap-2 overflow-x-auto rounded-lg border p-2 shadow-xs backdrop-blur",
        className,
      )}
      data-testid="vsfx-toolbar"
    >
      {groups.map((group) => {
        if (group.type === "toggles") {
          return (
            <ToggleGroup
              className="max-w-full flex-wrap"
              key={group.id}
              onValueChange={(nextValue) => {
                if (!nextValue) {
                  return;
                }

                const nextItem = group.items.find((item) => item.draggerName === nextValue);

                if (!nextItem) {
                  return;
                }

                nextItem.run(context);
                setActiveDragger(nextValue);
              }}
              size="sm"
              type="single"
              value={activeDragger}
              variant="outline"
            >
              {group.items.map((item) => (
                <ToggleGroupItem
                  aria-label={item.label}
                  disabled={!hasViewer}
                  key={item.id}
                  value={item.draggerName ?? item.id}
                >
                  {item.label}
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
          );
        }

        return (
          <ButtonGroup className="max-w-full flex-wrap gap-2" key={group.id}>
            {group.items.map((item) => (
              <Button
                aria-label={item.label}
                disabled={item.selectionDependent ? !hasSelection : !hasViewer}
                key={item.id}
                onClick={() => {
                  item.run(context);
                }}
                size="sm"
                type="button"
                variant="outline"
              >
                {item.label}
              </Button>
            ))}
          </ButtonGroup>
        );
      })}
    </div>
  );
}
