"use client";

import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

export function Section({
  eyebrow,
  title,
  description,
  action,
  children,
  className,
  headerClassName,
}: {
  eyebrow?: string;
  title?: string;
  description?: string;
  action?: ReactNode;
  children?: ReactNode;
  className?: string;
  headerClassName?: string;
}) {
  const hasHeader =
    eyebrow != null || title != null || description != null || action != null;

  return (
    <section className={cn("flex min-w-0 flex-col gap-4 sm:gap-5", className)}>
      {hasHeader ? (
        <div
          className={cn(
            "flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between",
            headerClassName,
          )}
        >
          <div className="min-w-0 space-y-1.5">
            {eyebrow ? (
              <p className="text-primary text-[11px] font-semibold tracking-[0.14em] uppercase">
                {eyebrow}
              </p>
            ) : null}
            {title ? (
              <h2 className="text-lg font-semibold tracking-tight text-balance sm:text-xl">
                {title}
              </h2>
            ) : null}
            {description ? (
              <p className="text-muted-foreground max-w-2xl text-sm leading-relaxed">
                {description}
              </p>
            ) : null}
          </div>
          {action ? (
            <div className="flex shrink-0 flex-wrap items-center gap-2">
              {action}
            </div>
          ) : null}
        </div>
      ) : null}
      {children}
    </section>
  );
}
