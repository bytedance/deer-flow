"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useI18n } from "@/core/i18n/hooks";
import {
  DRAWER_COLOR_KEYS,
  DRAWER_COLORS,
  DRAWER_DEFAULT_COLOR,
  DRAWER_DEFAULT_ICON,
  DRAWER_ICON_KEYS,
  type CardDrawer,
  type DrawerColorKey,
  type DrawerIconKey,
} from "@/core/knowledge/card-drawers";
import { cn } from "@/lib/utils";

import { DRAWER_ICON_COMPONENTS } from "./drawer-icon";

/**
 * Create/edit dialog for a user-defined card drawer (2026-09-04). Deliberately
 * sparse, mirroring Qoder's "create workspace": a name field, an icon grid and
 * a color grid — both 12 cells, single row, column-aligned — and no descriptive
 * prose. `initial` null = create; non-null pre-fills for edit. Save is disabled
 * until the name is non-blank.
 */
export function DrawerEditor({
  open,
  initial,
  onOpenChange,
  onSubmit,
}: {
  open: boolean;
  initial: CardDrawer | null;
  onOpenChange: (open: boolean) => void;
  onSubmit: (name: string, icon: DrawerIconKey, color: DrawerColorKey) => void;
}) {
  const { t } = useI18n();
  const td = t.knowledge.manualCards.drawers;
  const [name, setName] = useState(initial?.name ?? "");
  const [icon, setIcon] = useState<DrawerIconKey>(
    initial?.icon ?? DRAWER_DEFAULT_ICON,
  );
  const [color, setColor] = useState<DrawerColorKey>(
    initial?.color ?? DRAWER_DEFAULT_COLOR,
  );
  const canSave = name.trim().length > 0;

  const handleSubmit = () => {
    if (!canSave) return;
    onSubmit(name.trim(), icon, color);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      {/* aria-describedby=undefined：刻意不放 DialogDescription（精简弹窗），
          显式告知 Radix 免得其 a11y 告警。 */}
      <DialogContent aria-describedby={undefined} className="sm:max-w-[560px]">
        <DialogHeader>
          <DialogTitle>{initial ? td.edit : td.new}</DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="drawer-name">{td.nameLabel}</Label>
            <Input
              id="drawer-name"
              data-testid="drawer-editor-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") handleSubmit();
              }}
              placeholder={td.namePlaceholder}
            />
          </div>

          <div className="flex flex-col gap-2">
            <Label>{td.iconLabel}</Label>
            <div className="grid grid-cols-12 gap-2">
              {DRAWER_ICON_KEYS.map((key) => {
                const Glyph = DRAWER_ICON_COMPONENTS[key];
                const selected = icon === key;
                const accent = DRAWER_COLORS[color].accent;
                return (
                  <button
                    aria-label={key}
                    aria-pressed={selected}
                    className={cn(
                      "text-muted-foreground flex aspect-square w-full items-center justify-center rounded-lg border transition-colors",
                      selected
                        ? "border-2"
                        : "border-border/60 hover:bg-muted/50",
                    )}
                    data-testid={`drawer-icon-${key}`}
                    key={key}
                    style={
                      selected
                        ? {
                            backgroundColor: `${accent}1F`,
                            borderColor: accent,
                            color: accent,
                          }
                        : undefined
                    }
                    type="button"
                    onClick={() => setIcon(key)}
                  >
                    <Glyph className="size-[18px]" />
                  </button>
                );
              })}
            </div>
          </div>

          <div className="flex flex-col gap-2">
            <Label>{td.colorLabel}</Label>
            <div className="grid grid-cols-12 gap-2">
              {DRAWER_COLOR_KEYS.map((key) => {
                const selected = color === key;
                const accent = DRAWER_COLORS[key].accent;
                return (
                  <div
                    className="flex aspect-square w-full items-center justify-center"
                    key={key}
                  >
                    <button
                      aria-label={key}
                      aria-pressed={selected}
                      className="size-[22px] rounded-full transition-transform hover:scale-110"
                      data-testid={`drawer-color-${key}`}
                      style={{
                        backgroundColor: accent,
                        outline: selected ? `2px solid ${accent}` : undefined,
                        outlineOffset: selected ? 2 : undefined,
                      }}
                      type="button"
                      onClick={() => setColor(key)}
                    />
                  </div>
                );
              })}
            </div>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t.common.cancel}
          </Button>
          <Button
            className="bg-[#16A34A] text-white hover:bg-[#15913F]"
            data-testid="drawer-editor-submit"
            disabled={!canSave}
            onClick={handleSubmit}
          >
            {initial ? td.save : td.create}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
