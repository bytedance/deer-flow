"use client";

import {
  ArrowUpRightIcon,
  PuzzleIcon,
  SparklesIcon,
  type LucideIcon,
} from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

const tones = [
  "bg-sky-50 text-sky-600 dark:bg-sky-950 dark:text-sky-300",
  "bg-amber-50 text-amber-700 dark:bg-amber-950 dark:text-amber-300",
  "bg-violet-50 text-violet-600 dark:bg-violet-950 dark:text-violet-300",
  "bg-emerald-50 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300",
];

export function CapabilityIcon({
  name,
  skill = false,
  icon: CustomIcon,
}: {
  name: string;
  skill?: boolean;
  icon?: LucideIcon;
}) {
  const tone =
    [...name].reduce((value, char) => value + char.charCodeAt(0), 0) %
    tones.length;
  const Icon = CustomIcon ?? (skill ? SparklesIcon : PuzzleIcon);
  return (
    <div
      className={cn(
        "flex size-12 shrink-0 items-center justify-center rounded-2xl",
        tones[tone],
      )}
    >
      <Icon className="size-6" strokeWidth={1.6} />
    </div>
  );
}

export function CapabilityCard({
  name,
  description,
  label,
  icon,
  status,
  children,
  onDetails,
  detailsLabel,
}: {
  name: string;
  description: string;
  label: string;
  icon: ReactNode;
  status?: ReactNode;
  children: ReactNode;
  onDetails?: () => void;
  detailsLabel?: string;
}) {
  return (
    <article className="bg-background group hover:border-foreground/20 flex min-w-0 flex-col rounded-2xl border p-5 transition-[border-color,box-shadow] hover:shadow-sm">
      <div className="mb-5 flex items-start justify-between gap-3">
        {icon}
        <span className="text-muted-foreground bg-muted/60 rounded-md px-2 py-1 text-[11px] font-medium">
          {label}
        </span>
      </div>
      <h3 className="min-w-0 text-base font-semibold tracking-tight">
        {onDetails ? (
          <button
            className="hover:text-muted-foreground flex max-w-full items-center gap-1.5 text-left"
            onClick={onDetails}
            aria-label={detailsLabel}
          >
            <span className="truncate">{name}</span>
            <ArrowUpRightIcon className="size-3.5 shrink-0 opacity-0 transition-opacity group-hover:opacity-60" />
          </button>
        ) : (
          <span className="block truncate">{name}</span>
        )}
      </h3>
      <p className="text-muted-foreground mt-2 line-clamp-2 min-h-10 text-[13px] leading-5">
        {description}
      </p>
      <div className="mt-6 flex min-h-8 items-center justify-between gap-2 border-t pt-4">
        <div className="text-muted-foreground flex min-w-0 items-center gap-1.5 text-xs">
          {status}
        </div>
        <div className="flex shrink-0 items-center gap-1">{children}</div>
      </div>
    </article>
  );
}
