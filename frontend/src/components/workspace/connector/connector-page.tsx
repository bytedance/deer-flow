"use client";

import { useQueryClient } from "@tanstack/react-query";
import { LoaderCircleIcon, PlugIcon, SearchIcon } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  WorkspaceBody,
  WorkspaceContainer,
} from "@/components/workspace/workspace-container";
import { WorkspaceGalleryHeader } from "@/components/workspace/workspace-gallery-header";
import {
  useConnectorConnections,
  useConnectorProviders,
  useDisconnectConnection,
  useOAuthAuthorize,
  useSaveConnection,
} from "@/core/connector/hooks";
import { useI18n } from "@/core/i18n/hooks";

function providerIconSrc(service: string): string {
  return `/connector-icons/${service}.png`;
}

function providerIconFallback(
  e: React.SyntheticEvent<HTMLImageElement>,
  homepageUrl?: string,
): void {
  const img = e.target as HTMLImageElement;
  if (!homepageUrl) return;
  try {
    const domain = new URL(homepageUrl).hostname;
    img.src = `https://www.google.com/s2/favicons?domain=${domain}&sz=32`;
  } catch {
    img.style.display = "none";
  }
}

export function ConnectorPage() {
  const { t } = useI18n();
  const tp = t.connectorPage;
  const { providers, isLoading, error } = useConnectorProviders();
  const { connections } = useConnectorConnections();
  const saveConnection = useSaveConnection();
  const disconnectConnection = useDisconnectConnection();
  const oauthAuthorize = useOAuthAuthorize();
  const queryClient = useQueryClient();

  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<
    "all" | "connected" | "disconnected"
  >("all");
  const [categoryFilter, setCategoryFilter] = useState<string | null>(null);
  const [credentialDialog, setCredentialDialog] = useState<{
    service: string;
    displayName: string;
    type: "api_key" | "custom_credential";
    fields: {
      key: string;
      label: string;
      inputType: "text" | "password";
      required: boolean;
      placeholder?: string;
      description?: string;
    }[];
  } | null>(null);
  const [credentialValues, setCredentialValues] = useState<
    Record<string, string>
  >({});

  const connectedMap = new Map(connections.map((c) => [c.service, c]));
  // Platform-level: configured by admin, user cannot disconnect
  const isPlatformConnected = (p: (typeof providers)[number]) =>
    p.apiKeyConfigured === true || p.customCredentialConfigured === true;
  // User-level: connected by this user, can disconnect
  const isUserConnected = (p: (typeof providers)[number]) => {
    const conn = connectedMap.get(p.service);
    return conn != null && conn.isDefault !== true;
  };
  const isAnyConnected = (p: (typeof providers)[number]) =>
    isPlatformConnected(p) || isUserConnected(p);
  const connectedCount = providers.filter(isAnyConnected).length;

  const normalizeCategory = (c: unknown): string => {
    if (typeof c === "string") return c;
    if (c == null || typeof c !== "object") return "";
    const obj = c as Record<string, unknown>;
    const val = obj.name ?? obj.label ?? obj.displayName ?? obj.title;
    if (typeof val === "string") return val;
    if (typeof val === "number") return String(val);
    return "";
  };

  // Build category list sorted by frequency
  const categoryCounts = new Map<string, number>();
  for (const p of providers) {
    for (const c of p.categories) {
      const name = normalizeCategory(c);
      if (!name) continue;
      categoryCounts.set(name, (categoryCounts.get(name) ?? 0) + 1);
    }
  }
  const topCategories = Array.from(categoryCounts.entries())
    .sort((a, b) => b[1] - a[1])
    .slice(0, 10)
    .map(([name]) => name);

  const filtered = providers.filter((p) => {
    const catNames = p.categories.map(normalizeCategory).filter(Boolean);
    const isConnected = isAnyConnected(p);
    if (statusFilter === "connected" && !isConnected) return false;
    if (statusFilter === "disconnected" && isConnected) return false;
    if (categoryFilter && !catNames.includes(categoryFilter)) return false;
    if (!search.trim()) return true;
    const q = search.toLowerCase();
    return [p.service, p.displayName, ...catNames].some((s) =>
      s.toLowerCase().includes(q),
    );
  });

  const openCredentialDialog = (provider: (typeof providers)[number]) => {
    const authConfig = provider.auth?.find(
      (a) => a.type === "custom_credential" || a.type === "api_key",
    );
    if (authConfig?.type === "custom_credential" && authConfig.fields?.length) {
      setCredentialDialog({
        service: provider.service,
        displayName: provider.displayName,
        type: "custom_credential",
        fields: authConfig.fields,
      });
      setCredentialValues({});
    } else if (authConfig?.type === "api_key") {
      // Render every field declared by the provider, preserving keys,
      // types, required flags, placeholders, and descriptions.
      const providerFields = authConfig.fields?.length
        ? authConfig.fields
        : [
            {
              key: "apiKey",
              label: "API Key",
              inputType: "password" as const,
              required: true,
              placeholder: "sk-…",
            },
          ];
      setCredentialDialog({
        service: provider.service,
        displayName: provider.displayName,
        type: "api_key",
        fields: providerFields,
      });
      setCredentialValues({});
    } else if (provider.authTypes.includes("custom_credential")) {
      // Fallback: auth config was empty — show generic key-value editor
      setCredentialDialog({
        service: provider.service,
        displayName: provider.displayName,
        type: "custom_credential",
        fields: [],
      });
      setCredentialValues({});
    } else if (provider.authTypes.includes("api_key")) {
      // Fallback: auth config was empty — show generic API key input
      setCredentialDialog({
        service: provider.service,
        displayName: provider.displayName,
        type: "api_key",
        fields: [
          {
            key: "apiKey",
            label: "API Key",
            inputType: "password",
            required: true,
            placeholder: "sk-…",
          },
        ],
      });
      setCredentialValues({});
    }
  };

  const handleCredentialConnect = async () => {
    if (!credentialDialog) return;
    const values: Record<string, string> = {};
    for (const field of credentialDialog.fields) {
      const raw = credentialValues[field.key];
      if (field.required && !raw?.trim()) return;
      if (raw) values[field.key] = raw.trim();
    }
    const authType =
      credentialDialog.type === "custom_credential"
        ? "custom_credential"
        : "api_key";
    try {
      await saveConnection.mutateAsync({
        service: credentialDialog.service,
        body: { authType, values },
      });
      toast.success(tp.connectedToast(credentialDialog.displayName));
      setCredentialDialog(null);
      setCredentialValues({});
    } catch (e) {
      toast.error(e instanceof Error ? e.message : tp.connectFailed);
    }
  };

  const handleOAuthConnect = async (service: string) => {
    // Open a blank window synchronously inside the user gesture so
    // browsers do not block it as an unsolicited popup.
    const popup = window.open("about:blank", "_blank", "width=600,height=700");
    try {
      const result = await oauthAuthorize.mutateAsync(service);
      if (result.url) {
        if (popup) {
          popup.location.href = result.url;
        } else {
          // Fallback when the popup was blocked — open in the same tab.
          window.location.href = result.url;
        }
        const check = setInterval(() => {
          if (!popup || popup.closed) {
            clearInterval(check);
            void queryClient.invalidateQueries({
              queryKey: ["connectorConnections"],
            });
            void queryClient.invalidateQueries({
              queryKey: ["connectorProviders"],
            });
          }
        }, 500);
      } else {
        popup?.close();
      }
    } catch (e) {
      popup?.close();
      toast.error(e instanceof Error ? e.message : tp.connectFailed);
    }
  };

  return (
    <WorkspaceContainer>
      <WorkspaceBody>
        <div className="flex size-full flex-col overflow-y-auto">
          <div className="mx-auto w-full max-w-(--container-width-lg) px-4 py-6 md:px-6">
            {/* Header */}
            <WorkspaceGalleryHeader
              icon={PlugIcon}
              title={tp.title}
              subtitle={
                connectedCount > 0
                  ? tp.subtitleConnected(connectedCount)
                  : tp.subtitleEmpty
              }
            />

            {/* Loading */}
            {isLoading && (
              <div className="text-muted-foreground flex h-48 items-center justify-center text-sm">
                {tp.loading}
              </div>
            )}

            {/* Error */}
            {error && !isLoading && (
              <div className="text-muted-foreground flex h-48 flex-col items-center justify-center gap-3 text-sm">
                <PlugIcon className="size-10" />
                <p>{tp.errorDescription}</p>
              </div>
            )}

            {/* Content */}
            {!isLoading && !error && (
              <div className="flex flex-col">
                {/* Search + filters */}
                <div className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
                  <div className="relative max-w-md flex-1">
                    <SearchIcon className="text-muted-foreground absolute top-1/2 left-3 size-4 -translate-y-1/2" />
                    <Input
                      className="h-10 rounded-full pl-9"
                      name="connector-search"
                      placeholder={tp.searchPlaceholder}
                      value={search}
                      onChange={(e) => setSearch(e.target.value)}
                      autoComplete="off"
                    />
                  </div>
                  <div className="flex items-center gap-1.5">
                    {(
                      [
                        ["all", tp.statusAll, providers.length],
                        ["connected", tp.statusConnected, connectedCount],
                        [
                          "disconnected",
                          tp.statusDisconnected,
                          providers.length - connectedCount,
                        ],
                      ] as const
                    ).map(([key, label, count]) => (
                      <button
                        key={key}
                        type="button"
                        onClick={() => setStatusFilter(key)}
                        className={
                          "rounded-full px-3 py-1.5 text-xs font-medium transition-colors" +
                          (statusFilter === key
                            ? " bg-foreground text-background"
                            : " bg-muted text-muted-foreground hover:bg-muted/80")
                        }
                      >
                        {label}
                        <span className="ml-1 opacity-60">{count}</span>
                      </button>
                    ))}
                  </div>
                </div>

                {topCategories.length > 0 && (
                  <div className="-mx-1 mb-4 flex flex-wrap items-center gap-1">
                    {topCategories.map((cat) => (
                      <button
                        key={
                          typeof cat === "string" ? cat : JSON.stringify(cat)
                        }
                        type="button"
                        onClick={() =>
                          setCategoryFilter(categoryFilter === cat ? null : cat)
                        }
                        className={
                          "rounded-full px-3 py-1 text-xs font-medium transition-colors" +
                          (categoryFilter === cat
                            ? " bg-foreground text-background"
                            : " bg-muted text-muted-foreground hover:bg-muted/80")
                        }
                      >
                        {cat}
                      </button>
                    ))}
                    {categoryFilter && (
                      <button
                        type="button"
                        onClick={() => setCategoryFilter(null)}
                        className="text-muted-foreground hover:text-foreground rounded-full px-2 py-1 text-xs transition-colors"
                      >
                        {tp.clearFilter}
                      </button>
                    )}
                  </div>
                )}

                {filtered.length > 0 && (
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
                    {filtered.map((provider) => {
                      const isConnected = isAnyConnected(provider);
                      const canDisconnect = isUserConnected(provider);
                      const isSaving =
                        saveConnection.isPending &&
                        saveConnection.variables?.service === provider.service;
                      const hasApiKey = provider.authTypes.includes("api_key");
                      const hasCustom =
                        provider.authTypes.includes("custom_credential");

                      return (
                        <Card
                          key={provider.service}
                          className="flex flex-col overflow-hidden !px-3 !pt-3 !pb-2 shadow-none"
                        >
                          <CardHeader className="flex-1 space-y-0 !p-0">
                            <div className="flex min-w-0 items-center gap-2">
                              <img
                                src={providerIconSrc(provider.service)}
                                alt=""
                                className="size-5 shrink-0 rounded"
                                loading="lazy"
                                onError={(e) =>
                                  providerIconFallback(e, provider.homepageUrl)
                                }
                              />
                              <span className="min-w-0 flex-1 truncate text-sm leading-tight font-medium">
                                {provider.displayName}
                              </span>
                            </div>
                            <CardDescription className="truncate text-xs">
                              {provider.service}
                              {provider.categories
                                .map(normalizeCategory)
                                .filter(Boolean).length > 0 &&
                                ` · ${provider.categories.map(normalizeCategory).filter(Boolean).slice(0, 2).join(", ")}`}
                            </CardDescription>
                          </CardHeader>
                          <CardFooter className="flex items-center justify-between !px-0 !pt-2 !pb-0">
                            <span className="text-muted-foreground text-xs">
                              {isConnected ? tp.connected : ""}
                            </span>
                            <div className="flex items-center gap-1.5">
                              {canDisconnect ? (
                                <Button
                                  variant="outline"
                                  size="sm"
                                  className="h-7 shrink-0 px-2 text-xs"
                                  disabled={
                                    disconnectConnection.isPending &&
                                    disconnectConnection.variables ===
                                      provider.service
                                  }
                                  onClick={() =>
                                    disconnectConnection.mutate(
                                      provider.service,
                                    )
                                  }
                                >
                                  {disconnectConnection.isPending &&
                                  disconnectConnection.variables ===
                                    provider.service
                                    ? "..."
                                    : tp.disconnect}
                                </Button>
                              ) : null}
                              {!isConnected &&
                              provider.oauthConfigured === true ? (
                                <Button
                                  variant="secondary"
                                  size="sm"
                                  className="h-7 shrink-0 px-2 text-xs"
                                  disabled={oauthAuthorize.isPending}
                                  onClick={() =>
                                    handleOAuthConnect(provider.service)
                                  }
                                >
                                  {tp.connectOAuth}
                                </Button>
                              ) : null}
                              {!isConnected &&
                              provider.oauthConfigured !== true &&
                              (hasApiKey || hasCustom) ? (
                                <Button
                                  variant="secondary"
                                  size="sm"
                                  className="h-7 shrink-0 px-2 text-xs"
                                  disabled={isSaving}
                                  onClick={() => openCredentialDialog(provider)}
                                >
                                  {tp.connect}
                                </Button>
                              ) : null}
                              {!isConnected &&
                              provider.oauthConfigured !== true &&
                              !hasApiKey &&
                              !hasCustom ? (
                                <Button
                                  variant="secondary"
                                  size="sm"
                                  className="h-7 shrink-0 px-2 text-xs"
                                  disabled={isSaving}
                                  onClick={() =>
                                    saveConnection.mutate({
                                      service: provider.service,
                                      body: { authType: "none" },
                                    })
                                  }
                                >
                                  {tp.connect}
                                </Button>
                              ) : null}
                            </div>
                          </CardFooter>
                        </Card>
                      );
                    })}
                  </div>
                )}

                {filtered.length === 0 && providers.length > 0 && (
                  <div className="flex flex-col items-center gap-2 py-16 text-center">
                    <SearchIcon className="text-muted-foreground size-10" />
                    <p className="text-muted-foreground text-sm">
                      {tp.noResults}
                    </p>
                  </div>
                )}

                {providers.length === 0 && (
                  <div className="flex flex-col items-center gap-2 py-16 text-center">
                    <PlugIcon className="text-muted-foreground size-10" />
                    <p className="text-muted-foreground text-sm">
                      {tp.noProvidersAvailable}
                    </p>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </WorkspaceBody>

      {/* Credential dialog */}
      {credentialDialog && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <Card className="w-full max-w-sm">
            <form
              autoComplete="off"
              onSubmit={(e) => {
                e.preventDefault();
                void handleCredentialConnect();
              }}
            >
              <CardHeader>
                <CardTitle>
                  {tp.apiKeyDialogTitle(credentialDialog.displayName)}
                </CardTitle>
                <CardDescription>
                  {tp.apiKeyDialogDescription(credentialDialog.service)}
                </CardDescription>
              </CardHeader>
              <CardContent className="flex flex-col gap-3">
                {credentialDialog.fields.length > 0 ? (
                  credentialDialog.fields.map((field) => (
                    <div key={field.key} className="flex flex-col gap-1">
                      <label className="text-sm font-medium">
                        {field.label}
                        {field.required && (
                          <span className="text-red-500"> *</span>
                        )}
                      </label>
                      {field.description && (
                        <p className="text-muted-foreground text-xs">
                          {field.description}
                        </p>
                      )}
                      <Input
                        type={field.inputType}
                        name={`connector-cred-${field.key}`}
                        placeholder={field.placeholder}
                        value={credentialValues[field.key] ?? ""}
                        autoComplete={
                          field.inputType === "password"
                            ? "new-password"
                            : "off"
                        }
                        onChange={(e) =>
                          setCredentialValues((prev) => ({
                            ...prev,
                            [field.key]: e.target.value,
                          }))
                        }
                      />
                    </div>
                  ))
                ) : (
                  <p className="text-muted-foreground text-xs">
                    {tp.unknownFieldsHint}
                  </p>
                )}
                <div className="flex justify-end gap-2 pt-2">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      setCredentialDialog(null);
                      setCredentialValues({});
                    }}
                  >
                    {tp.cancel}
                  </Button>
                  <Button
                    size="sm"
                    disabled={
                      credentialDialog.fields.some(
                        (f) => f.required && !credentialValues[f.key]?.trim(),
                      ) || saveConnection.isPending
                    }
                    type="submit"
                  >
                    {saveConnection.isPending && (
                      <LoaderCircleIcon className="mr-1 size-3.5 animate-spin" />
                    )}
                    {tp.connect}
                  </Button>
                </div>
              </CardContent>
            </form>
          </Card>
        </div>
      )}
    </WorkspaceContainer>
  );
}
