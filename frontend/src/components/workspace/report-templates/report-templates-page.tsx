"use client";

import Link from "next/link";
import { useState } from "react";

import { useReportTemplates } from "@/core/report-templates";
import type { Visibility } from "@/core/report-templates/types";
import { cn } from "@/lib/utils";

const SCOPES: { value: Visibility; label: string }[] = [
  { value: "private", label: "我的模板" },
  { value: "tenant", label: "租户共享" },
  { value: "builtin", label: "预置模板" },
];

const STATUS_LABEL: Record<string, string> = {
  draft: "草稿",
  published: "已发布",
  archived: "已归档",
};

export function ReportTemplatesPage() {
  const [scope, setScope] = useState<Visibility>("private");
  const { templates, isLoading, error } = useReportTemplates(scope);

  return (
    <div className="flex h-full flex-col gap-4 p-6">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">报告模板</h1>
          <p className="text-muted-foreground mt-1 text-sm">
            管理自定义报告模板、版本和发布状态。新建模板请通过{" "}
            <Link
              className="underline underline-offset-2 hover:text-foreground"
              href="/workspace/agents/ai-report--custom/chats/new"
            >
              自定义模板智能体
            </Link>
            。
          </p>
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
        <div className="text-muted-foreground text-sm">加载中…</div>
      )}
      {error && (
        <div className="rounded border border-destructive bg-destructive/10 p-3 text-sm">
          加载失败：{String(error)}
        </div>
      )}
      {!isLoading && !error && templates.length === 0 && (
        <div className="rounded border border-dashed p-8 text-center text-sm text-muted-foreground">
          {scope === "private"
            ? `你还没有自定义模板。在自定义模板智能体里说"创建模板"开始。`
            : "暂无模板。"}
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
                  更新于 {new Date(tpl.updated_at).toLocaleString()}
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
