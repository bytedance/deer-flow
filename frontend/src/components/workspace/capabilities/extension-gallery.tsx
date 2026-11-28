"use client";

import {
  ArrowLeftIcon,
  ChevronDownIcon,
  ChevronRightIcon,
  CircleAlertIcon,
  InfoIcon,
  RefreshCwIcon,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useId, useState } from "react";

import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  extensionDirectory,
  type ExtensionCatalogEntry,
} from "@/core/extensions/catalog";
import {
  extensionDirectoryCategories,
  type ExtensionCategory,
} from "@/core/extensions/documentation";
import { useFrontendExtensions } from "@/core/extensions/hooks";
import { pluginPages } from "@/core/extensions/pages";
import { extensionIcon } from "@/core/extensions/registry";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

import { ExtensionDetail } from "./extension-detail";
import { PluginRow } from "./plugin-directory";

type CategoryFilter = "all" | ExtensionCategory;
type ScopeFilter = "all" | "installed";

function ExtensionIconTile({
  entry,
  active = false,
}: {
  entry: ExtensionCatalogEntry;
  active?: boolean;
}) {
  const Icon = extensionIcon(entry.loaded?.extension?.icon ?? entry.icon);
  return (
    <div
      className={cn(
        "flex size-12 shrink-0 items-center justify-center rounded-xl",
        active ? "bg-secondary text-foreground" : "bg-muted text-foreground/80",
      )}
    >
      <Icon className="size-5" />
    </div>
  );
}

function installedPriority(entry: ExtensionCatalogEntry) {
  if (entry.loaded?.error) return 0;
  if (entry.loaded?.settings.enabled === true) return 1;
  return 2;
}

function InstalledExtensionCard({
  entry,
  discoveryReady,
  onSelect,
}: {
  entry: ExtensionCatalogEntry;
  discoveryReady: boolean;
  onSelect: () => void;
}) {
  const { t } = useI18n();
  const loaded = entry.loaded;
  const failed = discoveryReady && !!loaded?.error;
  const enabled =
    discoveryReady && !failed && loaded?.settings.enabled === true;
  const primaryPage = enabled && loaded ? pluginPages([loaded])[0] : undefined;
  const statusLabel = failed
    ? t.extensions.moduleUnavailable
    : enabled
      ? loaded?.runtime_only
        ? t.extensions.detail.loaded
        : t.capabilities.enabled
      : t.capabilities.disabled;

  return (
    <article className="bg-card hover:bg-muted/35 flex min-w-0 items-center gap-4 rounded-xl border px-4 py-4 transition-colors">
      <ExtensionIconTile entry={entry} active={enabled} />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <h3 className="text-sm font-semibold">
            <button
              type="button"
              className="text-left underline-offset-4 hover:underline"
              onClick={onSelect}
            >
              {entry.title}
            </button>
          </h3>
          <span
            className={cn(
              "inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] leading-4 font-medium",
              enabled
                ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400"
                : failed
                  ? "bg-destructive/10 text-destructive"
                  : "bg-muted text-muted-foreground",
            )}
          >
            {enabled ? (
              <span className="size-1.5 rounded-full bg-emerald-500" />
            ) : failed ? (
              <CircleAlertIcon className="size-3" />
            ) : null}
            {statusLabel}
          </span>
        </div>
        <p className="text-muted-foreground mt-1.5 line-clamp-2 text-xs leading-5">
          {entry.description}
        </p>
      </div>
      <div className="flex shrink-0 items-center gap-1.5">
        {primaryPage && (
          <Button
            asChild
            variant="outline"
            size="sm"
            className="h-8 rounded-lg px-3 text-xs"
          >
            <Link
              href={primaryPage.href}
              aria-label={t.extensions.open(entry.title)}
            >
              {t.extensions.directory.openAction}
            </Link>
          </Button>
        )}
        <Button
          variant="ghost"
          size="icon"
          aria-label={t.extensions.view(entry.title)}
          onClick={onSelect}
        >
          <ChevronRightIcon />
        </Button>
      </div>
    </article>
  );
}

function CatalogExtensionRow({
  entry,
  onSelect,
}: {
  entry: ExtensionCatalogEntry;
  onSelect: () => void;
}) {
  const { t } = useI18n();
  return (
    <PluginRow
      name={entry.title}
      description={entry.description}
      icon={<ExtensionIconTile entry={entry} />}
      onDetails={onSelect}
    >
      <Button
        variant="ghost"
        size="icon"
        aria-label={t.extensions.view(entry.title)}
        onClick={onSelect}
      >
        <ChevronRightIcon />
      </Button>
    </PluginRow>
  );
}

export function ExtensionGallery({ query = "" }: { query?: string }) {
  const { t, locale } = useI18n();
  const dir = t.extensions.directory;
  const publicQuery = useFrontendExtensions();
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const groupId = useId();
  const [scope, setScope] = useState<ScopeFilter>("all");
  const [category, setCategory] = useState<CategoryFilter>("all");
  const [examplesExpanded, setExamplesExpanded] = useState(false);

  const selected = params.get("extension");
  const entries = extensionDirectory(
    publicQuery.data ?? [],
    t.extensions.catalog,
    locale,
  );
  const source = publicQuery;

  function select(namespace?: string) {
    const next = new URLSearchParams(params);
    next.set("tab", "extensions");
    if (namespace) next.set("extension", namespace);
    else next.delete("extension");
    router.replace(`${pathname}?${next.toString()}`, { scroll: false });
  }

  const status = source.isPending ? (
    <p role="status" className="text-muted-foreground text-sm">
      {t.extensions.loading}
    </p>
  ) : source.isError ? (
    <div role="alert" className="flex flex-wrap items-center gap-3 text-sm">
      <p>{t.extensions.unavailable}</p>
      <Button variant="outline" size="sm" onClick={() => void source.refetch()}>
        {t.extensions.retry}
      </Button>
    </div>
  ) : null;

  const reload = (
    <Button
      variant="ghost"
      size="sm"
      className="text-muted-foreground -mr-2"
      aria-label={t.extensions.reloadAll}
      onClick={() => window.location.reload()}
    >
      <RefreshCwIcon className="size-4" />
      <span className="hidden sm:inline">{t.extensions.reload}</span>
    </Button>
  );

  if (selected) {
    const entry = entries.find((item) => item.id === selected);
    return (
      <div className="space-y-6">
        <div className="flex items-center justify-between gap-2">
          <Button
            variant="ghost"
            size="sm"
            className="-ml-2.5"
            onClick={() => select()}
          >
            <ArrowLeftIcon />
            {t.extensions.all}
          </Button>
        </div>
        {status}
        {!entry ? (
          <p className="text-muted-foreground py-8">
            {t.extensions.notInstalled}
          </p>
        ) : (
          <ExtensionDetail
            entry={entry}
            discovery={
              source.isPending ? "pending" : source.isError ? "error" : "ready"
            }
          />
        )}
      </div>
    );
  }

  const hasInstalledExamples = entries.some(
    (entry) => !!entry.loaded && entry.category === "examples",
  );
  const hasOther = entries.some((entry) => entry.category === "other");
  const filterCategories: ExtensionCategory[] = [
    ...extensionDirectoryCategories.filter((key) => key !== "other"),
    ...(hasInstalledExamples ? (["examples"] as const) : []),
    ...(hasOther ? (["other"] as const) : []),
  ];
  const activeCategory: CategoryFilter =
    category !== "all" && !filterCategories.includes(category)
      ? "all"
      : category;

  const trimmedQuery = query.trim().toLowerCase();
  const isSearching = trimmedQuery.length > 0;
  const matchesQuery = (entry: ExtensionCatalogEntry) => {
    if (!isSearching) return true;
    const categoryLabel = dir.categories[entry.category];
    return `${entry.title} ${entry.description} ${entry.package ?? ""} ${entry.id} ${categoryLabel} ${entry.loaded?.title ?? ""} ${entry.loaded?.description ?? ""}`
      .toLowerCase()
      .includes(trimmedQuery);
  };
  const matchesCategory = (entry: ExtensionCatalogEntry) =>
    activeCategory === "all" || entry.category === activeCategory;

  const totalInstalled = entries.filter((entry) => !!entry.loaded).length;
  const installedVisible = entries
    .filter(
      (entry) =>
        !!entry.loaded && matchesCategory(entry) && matchesQuery(entry),
    )
    .sort((a, b) => installedPriority(a) - installedPriority(b));

  const catalogVisible =
    scope === "installed"
      ? []
      : entries.filter(
          (entry) =>
            !entry.loaded &&
            entry.category !== "examples" &&
            matchesCategory(entry) &&
            matchesQuery(entry),
        );

  const examplesVisible =
    scope === "installed" ||
    (activeCategory !== "all" && activeCategory !== "examples")
      ? []
      : entries.filter(
          (entry) =>
            !entry.loaded &&
            entry.category === "examples" &&
            matchesQuery(entry),
        );

  const showExamples =
    isSearching || examplesExpanded || activeCategory === "examples";
  const showInstalledSection =
    scope === "installed" || installedVisible.length > 0;
  const showCatalogSection = catalogVisible.length > 0;
  const showExamplesSection = examplesVisible.length > 0;
  const nothingMatched =
    scope === "all" &&
    !installedVisible.length &&
    !catalogVisible.length &&
    !examplesVisible.length;

  return (
    <div className="space-y-6">
      <div
        className="flex flex-wrap gap-1"
        role="group"
        aria-label={dir.allCategories}
      >
        {(["all", ...filterCategories] as const).map((key) => (
          <Button
            key={key}
            variant="ghost"
            size="sm"
            aria-pressed={activeCategory === key}
            onClick={() => setCategory(key)}
            className={cn(
              "rounded-lg px-3 text-xs font-normal",
              activeCategory === key
                ? "bg-muted text-foreground font-medium"
                : "text-muted-foreground",
            )}
          >
            {key === "all" ? dir.allCategories : dir.categories[key]}
          </Button>
        ))}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <Tabs
          value={scope}
          onValueChange={(value) => setScope(value as ScopeFilter)}
        >
          <TabsList>
            <TabsTrigger value="all">{t.extensions.all}</TabsTrigger>
            <TabsTrigger value="installed" className="gap-1.5">
              <span>{dir.installed}</span>
              {totalInstalled > 0 && (
                <span className="text-muted-foreground text-[11px] tabular-nums">
                  {totalInstalled}
                </span>
              )}
            </TabsTrigger>
          </TabsList>
        </Tabs>
        {reload}
      </div>

      <div className="bg-muted/35 text-muted-foreground flex items-start gap-2 rounded-xl px-3.5 py-2.5 text-xs leading-5">
        <InfoIcon className="mt-0.5 size-3.5 shrink-0" />
        <p>{t.extensions.deploymentHint}</p>
      </div>

      {status}

      {showInstalledSection && (
        <section aria-labelledby={`${groupId}-installed`} className="space-y-4">
          <div className="space-y-1">
            <div className="flex items-baseline gap-2.5">
              <h2 id={`${groupId}-installed`} className="text-xl font-semibold">
                {dir.installedTitle}
              </h2>
              <span className="text-muted-foreground/70 text-xs tabular-nums">
                {installedVisible.length}
              </span>
            </div>
            <p className="text-muted-foreground text-sm">{dir.installedHint}</p>
          </div>
          {installedVisible.length > 0 ? (
            <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
              {installedVisible.map((entry) => (
                <InstalledExtensionCard
                  key={entry.id}
                  entry={entry}
                  discoveryReady={!source.isPending && !source.isError}
                  onSelect={() => select(entry.id)}
                />
              ))}
            </div>
          ) : (
            <div className="text-muted-foreground rounded-xl border border-dashed px-6 py-10 text-center text-sm">
              <p>
                {totalInstalled === 0
                  ? dir.installedEmpty
                  : dir.installedFilteredEmpty}
              </p>
              {totalInstalled === 0 ? (
                <Button
                  variant="outline"
                  size="sm"
                  className="mt-4"
                  onClick={() => setScope("all")}
                >
                  {t.extensions.all}
                </Button>
              ) : activeCategory !== "all" ? (
                <Button
                  variant="outline"
                  size="sm"
                  className="mt-4"
                  onClick={() => setCategory("all")}
                >
                  {dir.allCategories}
                </Button>
              ) : null}
            </div>
          )}
        </section>
      )}

      {showCatalogSection && (
        <section
          aria-labelledby={`${groupId}-catalog`}
          className={cn("space-y-6", showInstalledSection && "border-t pt-8")}
        >
          <div className="space-y-1">
            <div className="flex items-baseline gap-2.5">
              <h2 id={`${groupId}-catalog`} className="text-xl font-semibold">
                {dir.catalogTitle}
              </h2>
              <span className="text-muted-foreground/70 text-xs tabular-nums">
                {catalogVisible.length}
              </span>
            </div>
            <p className="text-muted-foreground text-sm">{dir.catalogHint}</p>
          </div>

          <div className="space-y-7">
            {extensionDirectoryCategories.map((key) => {
              const items = catalogVisible.filter(
                (entry) => entry.category === key,
              );
              if (!items.length) return null;
              return (
                <div
                  key={key}
                  aria-labelledby={`${groupId}-cat-${key}`}
                  className="space-y-1"
                >
                  <div className="flex items-baseline gap-3 border-b pb-3">
                    <h3
                      id={`${groupId}-cat-${key}`}
                      className="text-base font-semibold"
                    >
                      {dir.categories[key]}
                    </h3>
                    <span className="text-muted-foreground/70 text-xs tabular-nums">
                      {items.length}
                    </span>
                    <span className="text-muted-foreground ml-auto hidden text-xs lg:block">
                      {dir.hints[key]}
                    </span>
                  </div>
                  <div className="grid grid-cols-1 gap-x-9 lg:grid-cols-2">
                    {items.map((entry) => (
                      <CatalogExtensionRow
                        key={entry.id}
                        entry={entry}
                        onSelect={() => select(entry.id)}
                      />
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        </section>
      )}

      {showExamplesSection && (
        <section
          aria-labelledby={`${groupId}-examples`}
          className={cn(
            "space-y-2",
            (showInstalledSection || showCatalogSection) && "border-t pt-6",
          )}
        >
          <button
            type="button"
            aria-expanded={showExamples}
            onClick={() => setExamplesExpanded((open) => !open)}
            className="hover:bg-muted/40 flex w-full items-center justify-between gap-4 rounded-xl px-3 py-3 text-left transition-colors"
          >
            <div className="min-w-0">
              <div className="flex items-baseline gap-2.5">
                <h2
                  id={`${groupId}-examples`}
                  className="text-muted-foreground text-sm font-semibold"
                >
                  {dir.examplesTitle}
                </h2>
                <span className="text-muted-foreground/70 text-xs tabular-nums">
                  {examplesVisible.length}
                </span>
              </div>
              <p className="text-muted-foreground mt-0.5 text-xs leading-5">
                {dir.examplesHint}
              </p>
            </div>
            <ChevronDownIcon
              className={cn(
                "text-muted-foreground size-4 shrink-0 transition-transform",
                showExamples && "rotate-180",
              )}
            />
          </button>
          {showExamples && (
            <div className="grid grid-cols-1 gap-x-9 lg:grid-cols-2">
              {examplesVisible.map((entry) => (
                <CatalogExtensionRow
                  key={entry.id}
                  entry={entry}
                  onSelect={() => select(entry.id)}
                />
              ))}
            </div>
          )}
        </section>
      )}

      {nothingMatched && (
        <div
          role="status"
          className="text-muted-foreground py-12 text-center text-sm"
        >
          <p>{t.extensions.noResults}</p>
          {activeCategory !== "all" && (
            <Button
              variant="outline"
              size="sm"
              className="mt-4"
              onClick={() => setCategory("all")}
            >
              {dir.allCategories}
            </Button>
          )}
        </div>
      )}
    </div>
  );
}
