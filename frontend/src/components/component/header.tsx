"use client";

import { ArrowLeftIcon } from "lucide-react";
import Link from "next/link";
import type { ComponentProps, ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

import {
  headerActionPlusGlyphClass,
  headerButtonClass,
  headerCreateEmphasisButtonClass,
} from "./styles";

export function HeaderActionPlusGlyph({ className }: { className?: string }) {
  return (
    <span aria-hidden className={cn(headerActionPlusGlyphClass, className)}>
      +
    </span>
  );
}

export function HeaderCreateButton({
  children,
  className,
  variant = "outline",
  size = "sm",
  emphasis = true,
  ...props
}: ComponentProps<typeof Button> & { emphasis?: boolean }) {
  return (
    <Button
      type="button"
      variant={emphasis ? "default" : variant}
      size={size}
      className={cn(
        headerButtonClass,
        emphasis && headerCreateEmphasisButtonClass,
        "[&_svg]:size-3",
        className,
      )}
      {...props}
    >
      <HeaderActionPlusGlyph />
      {children}
    </Button>
  );
}

export function HeaderOutlineButton({
  children,
  className,
  leading,
  variant = "outline",
  size = "sm",
  ...props
}: ComponentProps<typeof Button> & { leading?: ReactNode }) {
  return (
    <Button
      type="button"
      variant={variant}
      size={size}
      className={cn(headerButtonClass, className)}
      {...props}
    >
      {leading}
      {children}
    </Button>
  );
}

export function Header({
  backHref,
  title,
  titleMeta,
  description,
  actions,
  className,
}: {
  backHref: string;
  title: string;
  titleMeta?: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  className?: string;
}) {
  const { t } = useI18n();
  return (
    <header className={cn("flex flex-col gap-3", className)}>
      <div className="flex min-w-0 items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3">
          <Button asChild size="icon-sm" variant="ghost" className="-ml-2">
            <Link href={backHref}>
              <ArrowLeftIcon />
              <span className="sr-only">{t.common.back}</span>
            </Link>
          </Button>
          <div className="min-w-0 flex-1">
            <div className="flex min-w-0 flex-wrap items-center gap-x-2.5 gap-y-1">
              <h1 className="truncate text-xl font-semibold tracking-tight">
                {title}
              </h1>
              {titleMeta ? (
                <div className="flex max-w-full min-w-0 shrink items-center">
                  {titleMeta}
                </div>
              ) : null}
            </div>
            {description ? (
              <p className="text-muted-foreground line-clamp-2 text-sm leading-snug">
                {description}
              </p>
            ) : null}
          </div>
        </div>
        {actions ? (
          <div className="flex shrink-0 items-center gap-2">{actions}</div>
        ) : null}
      </div>
    </header>
  );
}
