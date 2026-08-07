"use client";

import { SearchIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

import {
  workspaceFieldFocusClass,
  workspaceToolbarSearchInputClass,
  dialogFormActionCancelGlyphClass,
} from "./styles";

export function Search({
  value,
  onChange,
  onClear,
  placeholder,
  className,
  autoFocus,
}: {
  value: string;
  onChange: (value: string) => void;
  onClear?: () => void;
  placeholder: string;
  className?: string;
  autoFocus?: boolean;
}) {
  const { t } = useI18n();

  const handleClear = () => {
    if (onClear) {
      onClear();
      return;
    }
    onChange("");
  };

  return (
    <div className={cn("relative min-w-0", className)}>
      <SearchIcon className="text-muted-foreground pointer-events-none absolute top-1/2 left-1.5 size-3 -translate-y-1/2" />
      <Input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        autoFocus={autoFocus}
        className={cn(
          "border-border/70 w-full bg-transparent pr-7 pl-6 text-xs shadow-none md:text-xs",
          workspaceToolbarSearchInputClass,
          "focus-visible:bg-transparent",
          workspaceFieldFocusClass,
        )}
        aria-label={t.common.search}
      />
      {value ? (
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          className="absolute top-1/2 right-0.5 -translate-y-1/2"
          aria-label={t.common.cancel}
          onClick={handleClear}
        >
          <span
            aria-hidden
            className={cn(dialogFormActionCancelGlyphClass, "text-xs")}
          >
            ×
          </span>
        </Button>
      ) : null}
    </div>
  );
}
