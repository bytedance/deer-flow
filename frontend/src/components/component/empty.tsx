"use client";

import type { ComponentProps, ReactNode } from "react";

import { cn } from "@/lib/utils";

export function PageEmptyState({
  title,
  description,
  className,
}: {
  title: string;
  description?: string;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-1 flex-col items-center justify-center px-4 py-16 text-center",
        "min-h-[min(28rem,calc(100dvh-14rem))]",
        className,
      )}
    >
      <div className="max-w-md space-y-2">
        <p className="text-foreground text-sm font-medium">{title}</p>
        {description ? (
          <p className="text-muted-foreground text-sm leading-relaxed">
            {description}
          </p>
        ) : null}
      </div>
    </div>
  );
}

export function InlineEmpty({
  children,
  className,
  align = "left",
  onClick,
}: {
  children: ReactNode;
  className?: string;
  align?: "left" | "center";
  onClick?: () => void;
}) {
  return (
    <div
      role={onClick ? "button" : undefined}
      tabIndex={onClick ? 0 : undefined}
      onClick={onClick}
      onKeyDown={
        onClick
          ? (e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                onClick();
              }
            }
          : undefined
      }
      className={cn(
        "text-muted-foreground border-border/50 bg-muted/30 rounded-2xl border border-dashed px-4 py-10 text-sm backdrop-blur-sm",
        align === "center" && "text-center",
        onClick &&
          "hover:bg-muted/50 focus-visible:ring-ring cursor-pointer transition-colors focus-visible:ring-[3px] focus-visible:outline-none",
        className,
      )}
    >
      {children}
    </div>
  );
}

export function ListEmpty({
  children,
  className,
  size = "default",
  align = "left",
}: {
  children: ReactNode;
  className?: string;
  size?: "default" | "compact";
  align?: "left" | "center";
}) {
  return (
    <InlineEmpty
      align={align}
      className={cn(
        "border-border/60 rounded-xl border border-dashed",
        size === "compact" ? "py-10" : "py-12",
        className,
      )}
    >
      {children}
    </InlineEmpty>
  );
}

export function PanelEmpty({
  className,
  align = "center",
  ...props
}: ComponentProps<typeof InlineEmpty>) {
  return (
    <InlineEmpty
      align={align}
      className={cn(
        "border-0 bg-transparent shadow-none backdrop-blur-none",
        "flex flex-1 flex-col justify-center",
        className,
      )}
      {...props}
    />
  );
}
