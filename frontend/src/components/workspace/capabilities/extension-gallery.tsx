"use client";

import {
  ArrowLeftIcon,
  ChevronRightIcon,
  CircleAlertIcon,
  CircleCheckIcon,
  CircleMinusIcon,
  ExternalLinkIcon,
  InfoIcon,
  RefreshCwIcon,
} from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  extensionDirectory,
  type ExtensionCatalogEntry,
} from "@/core/extensions/catalog";
import { useFrontendExtensions } from "@/core/extensions/hooks";
import { extensionIcon } from "@/core/extensions/registry";
import { useI18n } from "@/core/i18n/hooks";
import type { Translations } from "@/core/i18n/locales/types";

import { PluginRow } from "./plugin-directory";

function ExtensionIconTile({ entry }: { entry: ExtensionCatalogEntry }) {
  const Icon = extensionIcon(entry.loaded?.extension?.icon ?? entry.icon);
  return (
    <div className="bg-muted flex size-12 shrink-0 items-center justify-center rounded-xl">
      <Icon className="size-6" />
    </div>
  );
}

function ExtensionDetail({
  entry,
  copy,
}: {
  entry: ExtensionCatalogEntry;
  copy: Translations["extensions"];
}) {
  const { loaded } = entry;
  const notice = loaded?.error
    ? { icon: <CircleAlertIcon />, text: copy.moduleUnavailable }
    : !loaded
      ? { icon: <InfoIcon />, text: copy.catalogHint }
      : loaded.settings.enabled === true
        ? { icon: <CircleCheckIcon />, text: copy.enabledManaged }
        : { icon: <CircleMinusIcon />, text: copy.disabledManaged };
  return (
    <div className="space-y-6">
      <div className="flex items-start gap-4">
        <ExtensionIconTile entry={entry} />
        <div className="min-w-0 flex-1">
          <h2 className="text-xl font-semibold tracking-tight">
            {entry.title}
          </h2>
          <p className="text-muted-foreground mt-1.5 text-sm leading-6">
            {entry.description}
          </p>
          {entry.package && (
            <p className="text-muted-foreground mt-2 font-mono text-xs break-all">
              {entry.package}
            </p>
          )}
        </div>
      </div>
      <Alert
        role={loaded?.error ? "alert" : "note"}
        variant={loaded?.error ? "destructive" : "default"}
        className="[&>svg]:translate-y-2"
      >
        {notice.icon}
        <AlertDescription className="flex flex-wrap items-center justify-between gap-x-6 gap-y-3">
          <p className="min-w-0 grow basis-64 py-1">{notice.text}</p>
          {entry.guide && (
            <Button
              variant="outline"
              size="sm"
              className="text-foreground"
              asChild
            >
              <a href={entry.guide} target="_blank" rel="noopener noreferrer">
                {copy.installationGuide}
                <ExternalLinkIcon />
              </a>
            </Button>
          )}
        </AlertDescription>
      </Alert>
    </div>
  );
}

export function ExtensionGallery({ query = "" }: { query?: string }) {
  const { t } = useI18n();
  const publicQuery = useFrontendExtensions();
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const selected = params.get("extension");
  const entries = extensionDirectory(
    publicQuery.data ?? [],
    t.extensions.catalog,
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
      className="text-muted-foreground -mr-2.5"
      aria-label={t.extensions.reloadAll}
      onClick={() => window.location.reload()}
    >
      <RefreshCwIcon />
      <span className="hidden sm:inline">{t.extensions.reloadAll}</span>
    </Button>
  );
  if (selected) {
    const entry = entries.find((item) => item.id === selected);
    return (
      <div className="max-w-3xl space-y-6">
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
          {reload}
        </div>
        {status}
        {!entry ? (
          <p className="text-muted-foreground py-8">
            {t.extensions.notInstalled}
          </p>
        ) : (
          <ExtensionDetail entry={entry} copy={t.extensions} />
        )}
      </div>
    );
  }
  const visible = entries.filter((entry) =>
    `${entry.title} ${entry.description} ${entry.package ?? ""} ${entry.id} ${entry.loaded?.title ?? ""} ${entry.loaded?.description ?? ""}`
      .toLowerCase()
      .includes(query.trim().toLowerCase()),
  );
  return (
    <div className="space-y-5">
      <div className="flex items-start justify-between gap-6">
        <p className="text-muted-foreground max-w-3xl min-w-0 flex-1 text-sm leading-6">
          {t.extensions.deploymentHint}
        </p>
        {reload}
      </div>
      {status}
      <div className="grid gap-x-10 md:grid-cols-2">
        {visible.map((entry) => {
          const loaded = entry.loaded;
          return (
            <PluginRow
              key={entry.id}
              name={entry.title}
              description={entry.description}
              icon={<ExtensionIconTile entry={entry} />}
              label={
                loaded?.error
                  ? t.extensions.moduleUnavailable
                  : loaded
                    ? loaded.settings.enabled === true
                      ? t.capabilities.enabled
                      : t.capabilities.disabled
                    : t.extensions.catalogEntry
              }
              onDetails={() => select(entry.id)}
              detailsLabel={t.extensions.view(entry.title)}
            >
              <Button
                variant="ghost"
                size="icon"
                aria-label={t.extensions.open(entry.title)}
                onClick={() => select(entry.id)}
              >
                <ChevronRightIcon />
              </Button>
            </PluginRow>
          );
        })}
      </div>
      {!visible.length && (
        <p role="status" className="text-muted-foreground py-8">
          {t.extensions.noResults}
        </p>
      )}
    </div>
  );
}
