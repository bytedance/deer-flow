"use client";

import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

export function FormField({
  label,
  labelTrailing,
  hint,
  children,
  className,
  htmlFor,
}: {
  label?: string;
  labelTrailing?: ReactNode;
  hint?: ReactNode;
  children: ReactNode;
  className?: string;
  htmlFor?: string;
}) {
  return (
    <div className={cn("flex min-w-0 flex-col gap-1.5", className)}>
      {label || labelTrailing ? (
        <div className="flex min-w-0 items-center justify-between gap-2">
          {label ? (
            <label
              htmlFor={htmlFor}
              className="text-muted-foreground shrink-0 text-xs font-medium"
            >
              {label}
            </label>
          ) : (
            <span className="sr-only">Field</span>
          )}
          {labelTrailing ? (
            <div className="min-w-0 flex-1">{labelTrailing}</div>
          ) : null}
        </div>
      ) : null}
      {children}
      {hint ? (
        <div className="text-muted-foreground text-xs leading-snug">{hint}</div>
      ) : null}
    </div>
  );
}
