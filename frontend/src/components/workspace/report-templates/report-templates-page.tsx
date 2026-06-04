"use client";

import { PlusIcon, StoreIcon } from "@/components/ui/icons";
import Link from "next/link";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { useI18n } from "@/core/i18n/hooks";
import { useReportTemplates } from "@/core/report-templates";
import type { Visibility } from "@/core/report-templates/types";
import { cn } from "@/lib/utils";

export function ReportTemplatesPage() {
  const { t } = useI18n();
  const [scope, setScope] = useState<Visibility>("private");
  const { templates, isLoading, error } = useReportTemplates(scope);

  const SCOPES: { value: Visibility; label: string }[] = [
    { value: "private", label: t.marketplace.visibilityPrivate },
    { value: "tenant", label: t.marketplace.visibilityTenant },
    { value: "builtin", label: t.marketplace.visibilityBuiltin },
  ];

  const STATUS_LABEL: Record<string, string> = {
    draft: t.marketplace.statusDraft,
    published: t.marketplace.statusPublished,
    archived: t.marketplace.statusArchived,
  };

  return (
    <div className="flex h-full flex-col gap-4 p-6">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">{t.marketplace.pageTitle}</h1>
          <p className="text-muted-foreground mt-1 text-sm">
            {t.marketplace.pageDescription}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <Link
            href="/workspace/template-marketplace"
            className="text-muted-foreground hover:text-foreground text-sm transition-colors"
          >
            <StoreIcon className="mr-1 inline size-4" />
            {t.marketplace.templateMarketplace}
          </Link>
          <Button asChild>
            <Link href="/workspace/report-templates/new">
              <PlusIcon className="mr-1 size-4" />
              {t.marketplace.createTemplate}
            </Link>
          </Button>
        </div>
      </header>

      <nav className="flex gap-2 border-b">
        {SCOPES.map((option) => {
          const active = scope === option.value;
          return (
            <button
              key={option.value}
              type="button"
              className={cn(
                "px-4 py-2 text-sm font-medium transition-colors",
                active
                  ? "border-b-2 border-primary text-foreground"
                  : "text-muted-foreground hover:text-foreground",
              )}
              onClick={() => setScope(option.value)}
            >
              {option.label}
            </button>
          );
        })}
      </nav>

      {isLoading && (
        <div className="text-muted-foreground text-sm">{t.marketplace.loading}</div>
      )}
      {error && (
        <div className="rounded border border-destructive bg-destructive/10 p-3 text-sm">
          {t.marketplace.loadingFailed}：{String(error)}
        </div>
      )}
      {!isLoading && !error && templates.length === 0 && (
        <div className="rounded border border-dashed p-8 text-center text-sm text-muted-foreground">
          {scope === "private"
            ? t.marketplace.emptyMyTemplates
            : t.marketplace.emptyNoTemplates}
        </div>
      )}

      {!isLoading && !error && templates.length > 0 && (
        <ul className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
          {templates.map((tpl) => (
            <li key={tpl.id}>
              <Link
                href={`/workspace/report-templates/${tpl.id}`}
                className="flex h-full flex-col rounded-lg border bg-card p-4 transition-colors hover:border-primary hover:bg-accent"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="font-medium leading-tight">
                    {tpl.display_name || tpl.name}
                  </div>
                  <span
                    className={cn(
                      "rounded px-1.5 py-0.5 text-xs",
                      tpl.status === "published" &&
                        "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300",
                      tpl.status === "draft" &&
                        "bg-amber-500/15 text-amber-700 dark:text-amber-300",
                      tpl.status === "archived" &&
                        "bg-muted text-muted-foreground",
                    )}
                  >
                    {STATUS_LABEL[tpl.status] ?? tpl.status}
                  </span>
                </div>
                <div className="text-muted-foreground mt-1 text-xs">
                  {tpl.name} · v{tpl.current_version}
                </div>
                {tpl.tags.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1">
                    {tpl.tags.map((t) => (
                      <span
                        key={t}
                        className="rounded bg-muted px-1.5 py-0.5 text-xs text-muted-foreground"
                      >
                        {t}
                      </span>
                    ))}
                  </div>
                )}
                <div className="text-muted-foreground mt-auto pt-3 text-xs">
                  {t.marketplace.updatedAt} {new Date(tpl.updated_at).toLocaleString()}
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
