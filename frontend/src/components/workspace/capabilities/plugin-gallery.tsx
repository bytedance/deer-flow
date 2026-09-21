"use client";

import { useQueries, useQueryClient } from "@tanstack/react-query";
import { ArrowUpRightIcon } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useAuth } from "@/core/auth/AuthProvider";
import { capabilityCopy } from "@/core/capabilities/copy";
import {
  installationQuery,
  useCapabilityCatalog,
} from "@/core/capabilities/hooks";
import type { CapabilityInstallation } from "@/core/capabilities/types";
import { useI18n } from "@/core/i18n/hooks";
import type { Translations } from "@/core/i18n/locales/types";
import { isStaticWebsiteOnly } from "@/core/static-mode";
import { cn } from "@/lib/utils";

import { MCPPluginManager } from "./mcp-plugin-manager";
import { pluginSettingsAdapters } from "./plugin-adapters";
import {
  catalogText,
  pluginCategories,
  type PluginCategory,
} from "./plugin-catalog";
import {
  PluginDirectory,
  PluginRow,
  type PluginDirectoryEntry,
} from "./plugin-directory";
import { PluginIcon } from "./plugin-icon";

function getPluginStatusLabel(
  adapter: string,
  status: CapabilityInstallation | undefined,
  unavailable: boolean | undefined,
  t: Translations,
  labels: ReturnType<typeof capabilityCopy>,
) {
  if (unavailable) return labels.adapterError;
  if (status) {
    if (status.auth_status === "connected") return labels.connected;
    if (status.auth_status === "required") return labels.required;
    if (status.auth_status === "configured") return labels.configured;
    return labels.installed;
  }
  if (adapter === "guide") return t.capabilities.directory.candidate;
  if (adapter === "lark") return t.capabilities.notInstalled;
  return labels.notConfigured;
}

function getPluginActionLabel(
  adapter: string,
  installed: boolean,
  canManage: boolean,
  t: Translations,
) {
  if (installed) return t.capabilities.manage;
  if (adapter === "guide" || !canManage) return t.capabilities.directory.view;
  if (adapter === "lark") return t.common.install;
  return t.capabilities.configure;
}

export function PluginGallery({ query }: { query: string }) {
  const { t, locale } = useI18n();
  const copy = t.capabilities.directory;
  const labels = capabilityCopy(locale);
  const { user } = useAuth();
  const canManage = user?.system_role === "admin" && !isStaticWebsiteOnly();
  const directory = useCapabilityCatalog();
  const definitions = directory.data ?? [];
  const adapterNames = [
    ...new Set(
      definitions
        .map((item) => item.adapter)
        .filter((name) => name !== "guide"),
    ),
  ];
  const states = useQueries({ queries: adapterNames.map(installationQuery) });
  const client = useQueryClient();
  const [filter, setFilter] = useState("all");
  const [category, setCategory] = useState<PluginCategory | "all">("all");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const selected = definitions.find(
    (item) => item.id === (selectedId ?? params.get("plugin")),
  );
  function close() {
    setSelectedId(null);
    if (params.has("plugin")) {
      const next = new URLSearchParams(params);
      next.delete("plugin");
      router.replace(`${pathname}?${next.toString()}`);
    }
    void client.invalidateQueries({ queryKey: ["capabilities"] });
  }
  const installations = [
    ...new Map(
      states
        .flatMap((state) => state.data?.items ?? [])
        .map((item) => [item.id, item]),
    ).values(),
  ];
  const catalog: PluginDirectoryEntry[] = definitions
    .filter(
      (plugin) =>
        canManage ||
        !installations.some(
          (item) => item.adapter === "mcp" && item.plugin_id === plugin.id,
        ),
    )
    .map((plugin) => {
      const status = installations.find(
        (item) => item.plugin_id === plugin.id && item.installed,
      );
      const unavailable = states[adapterNames.indexOf(plugin.adapter)]?.isError;
      return {
        id: plugin.id,
        category: plugin.category,
        installed: !!status,
        search: `${Object.values(plugin.name).join(" ")} ${Object.values(plugin.description).join(" ")} ${plugin.aliases.join(" ")}`,
        node: (
          <PluginRow
            name={catalogText(plugin.name, locale)}
            description={catalogText(plugin.description, locale)}
            icon={
              <PluginIcon
                name={plugin.id}
                asset={plugin.icon}
                capabilityId={plugin.id}
              />
            }
            label={getPluginStatusLabel(
              plugin.adapter,
              status,
              unavailable,
              t,
              labels,
            )}
            onDetails={() => setSelectedId(plugin.id)}
            detailsLabel={`${t.capabilities.details} ${catalogText(plugin.name, locale)}`}
          >
            <Button
              size="sm"
              variant="outline"
              className="h-8 text-xs"
              aria-label={`${plugin.adapter === "guide" ? copy.guide : t.capabilities.configure} ${catalogText(plugin.name, locale)}`}
              onClick={() => setSelectedId(plugin.id)}
            >
              {getPluginActionLabel(plugin.adapter, !!status, canManage, t)}
            </Button>
          </PluginRow>
        ),
      };
    });
  // Non-admins see safe installation projections, not the administrator's raw config editor.
  if (!canManage)
    for (const item of installations.filter((item) => item.adapter === "mcp")) {
      const manifest = definitions.find(
        (plugin) => plugin.id === item.plugin_id,
      );
      catalog.push({
        id: item.id,
        category: manifest?.category ?? "custom",
        search: `${item.name} ${item.description}`,
        installed: true,
        node: (
          <PluginRow
            name={item.name}
            description={item.description}
            icon={
              <PluginIcon
                name={item.name}
                icon={item.icon}
                asset={manifest?.icon}
                capabilityId={manifest?.id}
              />
            }
            label={
              item.selectable === false
                ? labels.unavailable
                : item.enabled
                  ? t.capabilities.enabled
                  : t.capabilities.disabled
            }
          >
            <span className="text-muted-foreground text-xs">
              {item.auth_status === "required"
                ? labels.required
                : item.auth_status === "configured"
                  ? labels.configured
                  : labels.unknown}
            </span>
          </PluginRow>
        ),
      });
    }
  const toolbar = (
    <Tabs value={filter} onValueChange={setFilter}>
      <TabsList>
        <TabsTrigger value="all">{t.capabilities.allPlugins}</TabsTrigger>
        <TabsTrigger value="installed">{t.capabilities.installed}</TabsTrigger>
      </TabsList>
    </Tabs>
  );
  const Settings = selected
    ? pluginSettingsAdapters[selected.adapter]
    : undefined;
  return (
    <div className="space-y-6">
      <div
        className="flex flex-wrap gap-1"
        role="group"
        aria-label={copy.allCategories}
      >
        {(
          [
            "all",
            ...pluginCategories.filter((key) => key !== "custom"),
          ] as const
        ).map((key) => (
          <Button
            key={key}
            variant="ghost"
            size="sm"
            aria-pressed={category === key}
            onClick={() => setCategory(key)}
            className={cn(
              "rounded-lg px-3 text-xs font-normal",
              category === key
                ? "bg-muted text-foreground font-medium"
                : "text-muted-foreground",
            )}
          >
            {key === "all" ? copy.allCategories : copy.categories[key]}
          </Button>
        ))}
      </div>
      {directory.isError && <p role="alert">{labels.catalogError}</p>}
      {directory.isLoading && <p role="status">{t.common.loading}</p>}
      {canManage ? (
        <MCPPluginManager
          query={query}
          toolbar={toolbar}
          category={category}
          installedOnly={filter === "installed"}
          catalog={catalog}
          definitions={definitions}
        />
      ) : (
        <>
          {toolbar}
          <PluginDirectory
            query={query}
            category={category}
            installedOnly={filter === "installed"}
            entries={catalog}
          />
        </>
      )}
      <Dialog open={!!selected} onOpenChange={(value) => !value && close()}>
        <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-2xl">
          {selected && (
            <>
              <DialogHeader>
                <PluginIcon
                  name={selected.id}
                  asset={selected.icon}
                  capabilityId={selected.id}
                />
                <DialogTitle>{catalogText(selected.name, locale)}</DialogTitle>
                <DialogDescription>
                  {catalogText(selected.description, locale)}
                </DialogDescription>
              </DialogHeader>
              {Settings ? (
                <Settings
                  key={selected.id}
                  plugin={selected}
                  onSaved={close}
                  canManage={canManage}
                />
              ) : (
                <p className="text-muted-foreground text-sm leading-6">
                  {catalogText(selected.setup, locale)}
                </p>
              )}
              <div className="text-muted-foreground flex items-center justify-between text-xs">
                <span>
                  {labels.version}: {selected.version}
                </span>
                <a
                  href={selected.source}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1 underline"
                >
                  {copy.source}
                  <ArrowUpRightIcon className="size-3" />
                </a>
              </div>
            </>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
