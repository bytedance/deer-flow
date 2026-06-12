"use client";

import {
  AlertCircleIcon,
  CheckCircle2Icon,
  LoaderCircleIcon,
  PlugIcon,
  UnplugIcon,
} from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Item,
  ItemActions,
  ItemContent,
  ItemDescription,
  ItemMedia,
  ItemTitle,
} from "@/components/ui/item";
import {
  useConfigureChannelProvider,
  useChannelConnections,
  useChannelProviders,
  useConnectChannelProvider,
  useDisconnectChannelProvider,
} from "@/core/channels/hooks";
import {
  closeConnectWindow,
  openConnectUrl,
  prepareConnectWindow,
} from "@/core/channels/open-connect-url";
import {
  providerCanConnect,
  providerCanEditRuntimeConfig,
  providerNeedsRuntimeConfig,
} from "@/core/channels/provider-state";
import type { ChannelConnection, ChannelProvider } from "@/core/channels/types";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

import { ChannelProviderIcon } from "../channels/channel-provider-icon";
import { ChannelRuntimeConfigDialog } from "../channels/channel-runtime-config-dialog";

import { SettingsSection } from "./settings-section";

function getProviderDescription(
  provider: ChannelProvider,
  descriptions: Record<string, string>,
): string {
  return descriptions[provider.provider] ?? provider.display_name;
}

function getConnectionLabel(connection: ChannelConnection): string | null {
  const account = connection.external_account_name;
  const workspace = connection.workspace_name;
  if (account && workspace) {
    return `${account} · ${workspace}`;
  }
  return account ?? workspace ?? connection.external_account_id ?? null;
}

function getStatusLabel(
  provider: ChannelProvider,
  connection: ChannelConnection | undefined,
  t: ReturnType<typeof useI18n>["t"],
): string {
  if (!provider.enabled) {
    return t.channels.disabled;
  }
  if (!provider.configured) {
    return t.channels.unconfigured;
  }
  if (provider.unavailable_reason) {
    return t.channels.unavailableShort;
  }
  const status = connection?.status ?? provider.connection_status;
  if (status === "connected") {
    return t.channels.connected;
  }
  if (status === "pending") {
    return t.channels.pending;
  }
  if (status === "revoked") {
    return t.channels.revoked;
  }
  return t.channels.notConnected;
}

function getProviderUnavailableReason(
  provider: ChannelProvider,
  t: ReturnType<typeof useI18n>["t"],
): string | undefined {
  if (provider.unavailable_reason) {
    return provider.unavailable_reason;
  }
  if (!provider.enabled) {
    return t.channels.disabled;
  }
  if (!provider.configured) {
    return t.channels.unconfigured;
  }
  return provider.unavailable_reason ?? undefined;
}

function ChannelProviderItem({
  provider,
  connection,
}: {
  provider: ChannelProvider;
  connection?: ChannelConnection;
}) {
  const { t } = useI18n();
  const connectMutation = useConnectChannelProvider();
  const configureMutation = useConfigureChannelProvider();
  const disconnectProviderMutation = useDisconnectChannelProvider();
  const [setupOpen, setSetupOpen] = useState(false);
  const isConnected =
    connection?.status === "connected" ||
    provider.connection_status === "connected";
  const canEditRuntimeConfig = providerCanEditRuntimeConfig(provider);
  const canConnect =
    (provider.connectable ?? (provider.enabled && provider.configured)) &&
    !isConnected;
  const isConnecting =
    (connectMutation.isPending &&
      connectMutation.variables === provider.provider) ||
    (configureMutation.isPending &&
      configureMutation.variables?.provider === provider.provider);
  const isDisconnecting =
    disconnectProviderMutation.isPending &&
    disconnectProviderMutation.variables === provider.provider;
  const connectionLabel = connection ? getConnectionLabel(connection) : null;
  const statusLabel = getStatusLabel(provider, connection, t);
  const unavailableReason = getProviderUnavailableReason(provider, t);

  const startConnect = (
    connectProvider: ChannelProvider,
    preparedWindow?: Window | null,
  ) => {
    const connectWindow =
      preparedWindow !== undefined
        ? preparedWindow
        : connectProvider.auth_mode === "deep_link"
          ? prepareConnectWindow()
          : null;
    void connectMutation
      .mutateAsync(connectProvider.provider)
      .then((result) => {
        if (result.url) {
          openConnectUrl(result.url, connectWindow);
          return;
        }
        closeConnectWindow(connectWindow);
        toast.success(result.instruction);
      })
      .catch((error) => {
        closeConnectWindow(connectWindow);
        toast.error(
          error instanceof Error ? error.message : t.channels.unavailable,
        );
      });
  };

  return (
    <>
      <Item variant="outline" className="w-full items-start">
        <ItemMedia variant="icon" className="bg-background">
          <ChannelProviderIcon
            provider={provider.provider}
            className="size-5"
          />
        </ItemMedia>
        <ItemContent className="min-w-0">
          <ItemTitle className="w-full">
            <span className="truncate">{provider.display_name}</span>
            <Badge
              variant={isConnected ? "default" : "outline"}
              className={cn(!isConnected && "text-muted-foreground")}
            >
              {isConnected ? <CheckCircle2Icon /> : <AlertCircleIcon />}
              {statusLabel}
            </Badge>
          </ItemTitle>
          <ItemDescription className="line-clamp-none">
            {getProviderDescription(provider, t.channels.descriptions)}
            {connectionLabel
              ? ` ${t.channels.connectedAs(connectionLabel)}`
              : ""}
            {!isConnected && provider.unavailable_reason
              ? ` ${provider.unavailable_reason}`
              : ""}
          </ItemDescription>
        </ItemContent>
        <ItemActions className="ml-auto">
          {isConnected ? (
            <>
              {canEditRuntimeConfig ? (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={isConnecting || isDisconnecting}
                  onClick={() => setSetupOpen(true)}
                >
                  {isConnecting ? (
                    <LoaderCircleIcon className="animate-spin" />
                  ) : (
                    <PlugIcon />
                  )}
                  {t.channels.modify}
                </Button>
              ) : null}
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={isDisconnecting}
                onClick={() => {
                  void disconnectProviderMutation
                    .mutateAsync(provider.provider)
                    .then(() => {
                      toast.success(t.channels.revoked);
                    })
                    .catch((error) => {
                      toast.error(
                        error instanceof Error
                          ? error.message
                          : t.channels.unavailable,
                      );
                    });
                }}
              >
                {isDisconnecting ? (
                  <LoaderCircleIcon className="animate-spin" />
                ) : (
                  <UnplugIcon />
                )}
                {t.channels.disconnect}
              </Button>
            </>
          ) : (
            <>
              {provider.configured && canEditRuntimeConfig ? (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={isConnecting || isDisconnecting}
                  onClick={() => setSetupOpen(true)}
                >
                  {t.channels.modify}
                </Button>
              ) : null}
              <Button
                type="button"
                size="sm"
                disabled={isConnecting}
                title={unavailableReason}
                onClick={() => {
                  if (providerNeedsRuntimeConfig(provider)) {
                    setSetupOpen(true);
                    return;
                  }

                  if (!canConnect) {
                    toast.error(unavailableReason ?? t.channels.unavailable);
                    return;
                  }

                  startConnect(provider);
                }}
              >
                {isConnecting ? (
                  <LoaderCircleIcon className="animate-spin" />
                ) : (
                  <PlugIcon />
                )}
                {connection?.status === "revoked"
                  ? t.channels.reconnect
                  : t.channels.connect}
              </Button>
            </>
          )}
        </ItemActions>
      </Item>
      <ChannelRuntimeConfigDialog
        provider={provider}
        open={setupOpen}
        submitting={configureMutation.isPending}
        onOpenChange={setSetupOpen}
        onSubmit={(submitProvider, values) => {
          const connectWindow =
            submitProvider.auth_mode === "deep_link"
              ? prepareConnectWindow()
              : null;
          void configureMutation
            .mutateAsync({ provider: submitProvider.provider, values })
            .then((updated) => {
              setSetupOpen(false);
              if (providerCanConnect(updated)) {
                startConnect(updated, connectWindow);
                return;
              }
              closeConnectWindow(connectWindow);
              toast.success(t.channels.connected);
            })
            .catch((error) => {
              closeConnectWindow(connectWindow);
              toast.error(
                error instanceof Error ? error.message : t.channels.unavailable,
              );
            });
        }}
      />
    </>
  );
}

export function ChannelsSettingsPage() {
  const { t } = useI18n();
  const {
    enabled,
    providers,
    isLoading: providersLoading,
    error: providersError,
  } = useChannelProviders();
  const {
    connections,
    isLoading: connectionsLoading,
    error: connectionsError,
  } = useChannelConnections();
  const isLoading = providersLoading || connectionsLoading;
  const error = providersError ?? connectionsError;
  const visibleProviders = providers.filter((provider) => provider.enabled);

  const connectionByProvider = new Map<string, ChannelConnection>();
  for (const connection of connections) {
    const existing = connectionByProvider.get(connection.provider);
    if (!existing || connection.status === "connected") {
      connectionByProvider.set(connection.provider, connection);
    }
  }

  return (
    <SettingsSection
      title={t.settings.channels.title}
      description={t.settings.channels.description}
    >
      {isLoading ? (
        <div className="text-muted-foreground text-sm">{t.common.loading}</div>
      ) : error ? (
        <div className="text-destructive text-sm">{t.channels.unavailable}</div>
      ) : !enabled ? (
        <div className="text-muted-foreground text-sm">
          {t.settings.channels.disabled}
        </div>
      ) : visibleProviders.length === 0 ? (
        <div className="text-muted-foreground text-sm">
          {t.settings.channels.disabled}
        </div>
      ) : (
        <div className="flex w-full flex-col gap-4">
          {visibleProviders.map((provider) => (
            <ChannelProviderItem
              key={provider.provider}
              provider={provider}
              connection={connectionByProvider.get(provider.provider)}
            />
          ))}
        </div>
      )}
    </SettingsSection>
  );
}
