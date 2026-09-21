"use client";

import { type ReactNode } from "react";

import { useI18n } from "@/core/i18n/hooks";

import { pluginCategories, type PluginCategory } from "./plugin-catalog";

export type PluginDirectoryEntry = {
  id: string;
  category: PluginCategory;
  search: string;
  installed: boolean;
  node: ReactNode;
};

export function PluginRow({
  name,
  description,
  icon,
  label,
  onDetails,
  detailsLabel,
  children,
}: {
  name: string;
  description: string;
  icon: ReactNode;
  label?: ReactNode;
  onDetails?: () => void;
  detailsLabel?: string;
  children: ReactNode;
}) {
  return (
    <article className="hover:bg-muted/40 group flex min-w-0 items-center gap-4 rounded-xl px-3 py-5 transition-colors">
      {icon}
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <h3 className="text-sm font-semibold">
            {onDetails ? (
              <button
                className="text-left underline-offset-4 hover:underline"
                onClick={onDetails}
                aria-label={detailsLabel}
              >
                {name}
              </button>
            ) : (
              name
            )}
          </h3>
          {label && (
            <span className="text-muted-foreground bg-muted/60 rounded px-1.5 py-0.5 text-[10px] leading-4">
              {label}
            </span>
          )}
        </div>
        <p className="text-muted-foreground mt-1.5 line-clamp-2 text-xs leading-5">
          {description}
        </p>
      </div>
      <div className="flex shrink-0 items-center gap-1">{children}</div>
    </article>
  );
}

export function PluginDirectory({
  entries,
  query = "",
  category = "all",
  installedOnly = false,
}: {
  entries: PluginDirectoryEntry[];
  query?: string;
  category?: PluginCategory | "all";
  installedOnly?: boolean;
}) {
  const { t } = useI18n();
  const copy = t.capabilities.directory;
  const visible = entries.filter(
    (entry) =>
      (!installedOnly || entry.installed) &&
      (category === "all" || entry.category === category) &&
      entry.search.toLowerCase().includes(query.trim().toLowerCase()),
  );
  if (!visible.length)
    return (
      <p
        className="text-muted-foreground py-12 text-center text-sm"
        role="status"
      >
        {t.capabilities.noResults}
      </p>
    );
  return (
    <div className="space-y-7">
      {pluginCategories.map((key) => {
        const items = visible.filter((entry) => entry.category === key);
        if (!items.length) return null;
        return (
          <section key={key} aria-labelledby={`plugin-group-${key}`}>
            <div className="flex items-baseline gap-3 border-b pb-3">
              <h2
                id={`plugin-group-${key}`}
                className="text-base font-semibold"
              >
                {copy.categories[key]}
              </h2>
              <span className="text-muted-foreground/70 text-xs">
                {items.length}
              </span>
              <span className="text-muted-foreground ml-auto hidden text-xs lg:block">
                {copy.hints[key]}
              </span>
            </div>
            <div className="grid grid-cols-1 gap-x-9 lg:grid-cols-2">
              {items.map((entry) => (
                <div key={entry.id} className="min-w-0">
                  {entry.node}
                </div>
              ))}
            </div>
          </section>
        );
      })}
    </div>
  );
}
