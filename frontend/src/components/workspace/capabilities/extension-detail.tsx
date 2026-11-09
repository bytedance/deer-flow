"use client";

import {
  ArrowRightIcon,
  BookOpenIcon,
  ChevronDownIcon,
  CircleAlertIcon,
  CircleCheckIcon,
  ExternalLinkIcon,
  RefreshCwIcon,
} from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import type { ExtensionCatalogEntry } from "@/core/extensions/catalog";
import { pluginPages, pluginPageTitle } from "@/core/extensions/pages";
import { extensionIcon } from "@/core/extensions/registry";
import { useI18n } from "@/core/i18n/hooks";

export function ExtensionDetail({
  entry,
  discovery,
}: {
  entry: ExtensionCatalogEntry;
  discovery: "pending" | "error" | "ready";
}) {
  const { t, locale } = useI18n();
  const copy = t.extensions;
  const { loaded } = entry;
  const available = discovery === "ready";
  const failed = available && !!loaded?.error;
  const enabled = available && !failed && loaded?.settings.enabled === true;
  const pages = enabled && loaded ? pluginPages([loaded]) : [];
  const primaryPage = pages[0];
  const Icon = extensionIcon(loaded?.extension?.icon ?? entry.icon);
  const label = !available
    ? discovery === "pending"
      ? copy.loading
      : copy.unavailable
    : failed
      ? copy.moduleUnavailable
      : !loaded
        ? copy.catalogEntry
        : enabled
          ? loaded?.runtime_only
            ? copy.detail.loaded
            : t.capabilities.enabled
          : t.capabilities.disabled;
  const hint = !available
    ? discovery === "pending"
      ? copy.loading
      : copy.unavailable
    : failed
      ? copy.detail.failedHint
      : !loaded
        ? copy.catalogHint
        : enabled
          ? loaded?.runtime_only
            ? copy.detail.loadedHint
            : copy.detail.readyHint
          : copy.detail.disabledHint;

  return (
    <article className="min-w-0 space-y-8">
      <header className="bg-card rounded-2xl border p-6 sm:p-8">
        <div className="flex flex-col gap-6 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex min-w-0 items-start gap-4 sm:gap-5">
            <div className="bg-muted flex size-14 shrink-0 items-center justify-center rounded-2xl sm:size-16">
              <Icon className="size-7 sm:size-8" />
            </div>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
                <h2 className="text-2xl font-semibold tracking-tight sm:text-[28px]">
                  {entry.title}
                </h2>
                <span
                  className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${
                    enabled
                      ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400"
                      : failed
                        ? "bg-destructive/10 text-destructive"
                        : "bg-muted text-muted-foreground"
                  }`}
                >
                  {enabled ? (
                    <CircleCheckIcon className="size-3.5" />
                  ) : failed ? (
                    <CircleAlertIcon className="size-3.5" />
                  ) : null}
                  {label}
                </span>
              </div>
              <p className="text-muted-foreground mt-3 max-w-2xl text-sm leading-7">
                {entry.description}
              </p>
            </div>
          </div>
          {primaryPage && (
            <Button asChild size="lg" className="h-11 shrink-0 rounded-xl px-5">
              <Link href={primaryPage.href}>
                {copy.open(
                  pages.length === 1
                    ? entry.title
                    : pluginPageTitle(primaryPage.surface, locale),
                )}
                <ArrowRightIcon />
              </Link>
            </Button>
          )}
        </div>
      </header>

      <div className="grid items-start gap-8 lg:grid-cols-[minmax(0,1fr)_20rem] lg:gap-12">
        <section
          className="min-w-0 px-1"
          aria-labelledby="extension-get-started"
        >
          <h3 id="extension-get-started" className="text-base font-semibold">
            {copy.detail.gettingStarted}
          </h3>
          {entry.gettingStarted?.length ? (
            <ol className="mt-6 space-y-6">
              {entry.gettingStarted.map((step, index) => (
                <li key={index} className="flex gap-4">
                  <span className="bg-muted text-muted-foreground flex size-8 shrink-0 items-center justify-center rounded-full text-xs font-medium tabular-nums">
                    {String(index + 1).padStart(2, "0")}
                  </span>
                  <div className="min-w-0 pt-1">
                    <h4 className="text-sm font-medium">{step.title}</h4>
                    <p className="text-muted-foreground mt-1.5 text-sm leading-6">
                      {step.description}
                    </p>
                  </div>
                </li>
              ))}
            </ol>
          ) : !pages.length ? (
            <p className="text-muted-foreground mt-4 text-sm leading-7">
              {enabled ? copy.detail.noPageHint : copy.detail.guideHint}
            </p>
          ) : null}
          {pages.length > (entry.gettingStarted?.length ? 1 : 0) && (
            <div className="mt-6 divide-y rounded-xl border px-4">
              {pages.map(({ surface, href }) => (
                <Link
                  key={href}
                  href={href}
                  className="hover:text-foreground text-muted-foreground flex items-center justify-between gap-3 py-4 text-sm transition-colors"
                >
                  {pluginPageTitle(surface, locale)}
                  <ArrowRightIcon className="size-4 shrink-0" />
                </Link>
              ))}
            </div>
          )}
        </section>

        <aside className="bg-muted/30 min-w-0 rounded-2xl p-6">
          {!!entry.requirements?.length && (
            <section
              className="mb-6 border-b pb-6"
              aria-labelledby="extension-requirements"
            >
              <h3 id="extension-requirements" className="text-sm font-semibold">
                {copy.detail.requirements}
              </h3>
              <ul className="text-muted-foreground mt-3 list-disc space-y-2 pl-4 text-sm leading-6">
                {entry.requirements.map((item, index) => (
                  <li key={index}>{item}</li>
                ))}
              </ul>
            </section>
          )}
          <h3 className="text-sm font-semibold">{copy.detail.management}</h3>
          <p
            role={failed ? "alert" : undefined}
            className="text-muted-foreground mt-3 text-sm leading-6"
          >
            {hint}
          </p>
          {entry.guide && (
            <a
              className="hover:text-muted-foreground mt-5 inline-flex items-center gap-2 text-sm font-medium transition-colors"
              href={entry.guide}
              target="_blank"
              rel="noopener noreferrer"
            >
              <BookOpenIcon className="size-4" />
              {copy.detail.guide}
              <ExternalLinkIcon className="size-3.5" />
            </a>
          )}
          <details className="group mt-6 border-t pt-5">
            <summary className="text-muted-foreground hover:text-foreground flex cursor-pointer list-none items-center justify-between gap-3 text-xs [&::-webkit-details-marker]:hidden">
              {copy.detail.technicalDetails}
              <ChevronDownIcon className="size-3.5 transition-transform group-open:rotate-180" />
            </summary>
            <dl className="mt-4 space-y-3 text-xs">
              {!!loaded?.model_tools?.length && (
                <div>
                  <dt className="text-muted-foreground">{copy.detail.tools}</dt>
                  <dd className="mt-1 font-mono break-all">
                    {loaded.model_tools.join(", ")}
                  </dd>
                </div>
              )}
              {entry.package && (
                <div>
                  <dt className="text-muted-foreground">
                    {copy.detail.package}
                  </dt>
                  <dd className="mt-1 font-mono break-all">{entry.package}</dd>
                </div>
              )}
              <div>
                <dt className="text-muted-foreground">
                  {copy.detail.namespace}
                </dt>
                <dd className="mt-1 font-mono break-all">{entry.id}</dd>
              </div>
            </dl>
            <p className="text-muted-foreground mt-5 text-xs leading-5">
              {copy.detail.refreshHint}
            </p>
            <Button
              variant="outline"
              size="sm"
              className="mt-3"
              onClick={() => window.location.reload()}
            >
              <RefreshCwIcon />
              {copy.detail.refresh}
            </Button>
          </details>
        </aside>
      </div>
    </article>
  );
}
