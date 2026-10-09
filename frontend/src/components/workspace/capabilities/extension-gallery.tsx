"use client";

import { ArrowLeftIcon, ChevronRightIcon } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useSyncExternalStore } from "react";

import { Button } from "@/components/ui/button";
import { extensionDirectory } from "@/core/extensions/catalog";
import { useFrontendExtensions } from "@/core/extensions/hooks";
import { extensionIcon } from "@/core/extensions/registry";
import { useI18n } from "@/core/i18n/hooks";

import { PluginRow } from "./plugin-directory";

const subscribeHydration = () => () => undefined;
const clientHydrated = () => true;
const serverHydrated = () => false;

export function ExtensionGallery({ query = "" }: { query?: string }) {
  // This dynamically loaded gallery can hydrate after its parent. Keep its
  // SSR buttons inert until its own navigation handlers are connected.
  const hydrated = useSyncExternalStore(
    subscribeHydration,
    clientHydrated,
    serverHydrated,
  );
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
    <p role="status">{t.extensions.loading}</p>
  ) : source.isError ? (
    <div role="alert">
      <p>{t.extensions.unavailable}</p>
      <Button
        variant="outline"
        disabled={!hydrated}
        onClick={() => void source.refetch()}
      >
        {t.extensions.retry}
      </Button>
    </div>
  ) : null;
  const reload = (
    <Button
      variant="outline"
      disabled={!hydrated}
      onClick={() => window.location.reload()}
    >
      {t.extensions.reloadAll}
    </Button>
  );
  if (selected) {
    const entry = entries.find((item) => item.id === selected);
    return (
      <div className="space-y-6">
        {reload}
        {status}
        <Button variant="ghost" disabled={!hydrated} onClick={() => select()}>
          <ArrowLeftIcon />
          {t.extensions.all}
        </Button>
        {!entry ? (
          <p>{t.extensions.notInstalled}</p>
        ) : (
          <div className="max-w-3xl space-y-4">
            <h2 className="text-2xl font-semibold">{entry.title}</h2>
            <p className="text-muted-foreground">{entry.description}</p>
            <p>
              {entry.loaded?.error
                ? t.extensions.moduleUnavailable
                : entry.loaded
                  ? entry.loaded.settings.enabled === true
                    ? t.extensions.enabledManaged
                    : t.extensions.disabledManaged
                  : t.extensions.catalogHint}
            </p>
            {entry.guide && (
              <Button variant="outline" asChild>
                <a href={entry.guide} target="_blank" rel="noopener noreferrer">
                  {t.extensions.installationGuide}
                </a>
              </Button>
            )}
          </div>
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
      {reload}
      {status}
      <p className="text-muted-foreground text-sm">
        {t.extensions.deploymentHint}
      </p>
      <div className="grid gap-x-10 md:grid-cols-2">
        {visible.map((entry) => {
          const loaded = entry.loaded;
          const Icon = extensionIcon(loaded?.extension?.icon ?? entry.icon);
          return (
            <PluginRow
              key={entry.id}
              name={entry.title}
              description={entry.description}
              icon={
                <div className="bg-muted flex size-12 shrink-0 items-center justify-center rounded-xl">
                  <Icon className="size-6" />
                </div>
              }
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
              detailsDisabled={!hydrated}
            >
              <Button
                variant="ghost"
                size="icon"
                aria-label={t.extensions.open(entry.title)}
                disabled={!hydrated}
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
