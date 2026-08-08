"use client";

import type { ReactNode } from "react";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";

import {
  selectTriggerWrapClass,
  workspaceToolbarSelectTriggerClass,
} from "./styles";

export type FormSelectOption = {
  value: string;
  label: ReactNode;
  textValue?: string;
  disabled?: boolean;
};

export function FormSelect({
  value,
  onValueChange,
  options,
  placeholder,
  disabled,
  className,
  contentClassName,
  contentAlign,
  size = "sm",
  triggerLabel,
  appearance = "dialog",
}: {
  value: string;
  onValueChange: (value: string) => void;
  options: FormSelectOption[];
  placeholder?: string;
  disabled?: boolean;
  className?: string;
  contentClassName?: string;
  contentAlign?: "start" | "center" | "end";
  size?: "sm" | "default";
  triggerLabel?: ReactNode;
  appearance?: "dialog" | "toolbar";
}) {
  return (
    <Select value={value} disabled={disabled} onValueChange={onValueChange}>
      <SelectTrigger
        size={size}
        className={cn(
          "w-full",
          appearance === "toolbar"
            ? workspaceToolbarSelectTriggerClass
            : selectTriggerWrapClass,
          className,
        )}
      >
        <SelectValue placeholder={placeholder}>{triggerLabel}</SelectValue>
      </SelectTrigger>
      <SelectContent align={contentAlign} className={contentClassName}>
        {options.map((option) => (
          <SelectItem
            key={option.value}
            value={option.value}
            disabled={option.disabled}
            textValue={
              option.textValue ??
              (typeof option.label === "string" ? option.label : option.value)
            }
          >
            {option.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
