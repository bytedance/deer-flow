"use client";

import {
  AlertCircleIcon,
  CheckCircle2Icon,
  LoaderCircleIcon,
  PlugIcon,
  UnplugIcon,
} from "lucide-react";

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
  useChannelConnections,
  useChannelProviders,
  useConnectChannelProvider,
  useDisconnectChannelConnection,
} from "@/core/channels/hooks";
import {
  closeConnectWindow,
  openConnectUrl,
  prepareConnectWindow,
} from "@/core/channels/open-connect-url";
import type { ChannelConnection, ChannelProvider } from "@/core/channels/types";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

import { ChannelProviderIcon } from "../channels/channel-provider-icon";

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

function ChannelProviderItem({
  provider,
  connection,
}: {
  provider: ChannelProvider;
  connection?: ChannelConnection;
}) {
  const { t } = useI18n();
  const connectMutation = useConnectChannelProvider();
  const disconnectMutation = useDisconnectChannelConnection();
  const isConnected = connection?.status === "connected";
  const canConnect = provider.enabled && provider.configured && !isConnected;
  const isConnecting =
    connectMutation.isPending &&
    connectMutation.variables === provider.provider;
  const isDisconnecting =
    disconnectMutation.isPending &&
    disconnectMutation.variables === connection?.id;
  const connectionLabel = connection ? getConnectionLabel(connection) : null;
  const statusLabel = getStatusLabel(provider, connection, t);

  return (
    <Item variant="outline" className="w-full items-start">
      <ItemMedia variant="icon" className="bg-background">
        <ChannelProviderIcon provider={provider.provider} className="size-5" />
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
          {connectionLabel ? ` ${t.channels.connectedAs(connectionLabel)}` : ""}
        </ItemDescription>
      </ItemContent>
      <ItemActions className="ml-auto">
        {isConnected && connection ? (
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={isDisconnecting}
            onClick={() => disconnectMutation.mutate(connection.id)}
          >
            {isDisconnecting ? (
              <LoaderCircleIcon className="animate-spin" />
            ) : (
              <UnplugIcon />
            )}
            {t.channels.disconnect}
          </Button>
        ) : (
          <Button
            type="button"
            size="sm"
            disabled={!canConnect || isConnecting}
            title={!provider.configured ? t.channels.unconfigured : undefined}
            onClick={() => {
              const connectWindow = prepareConnectWindow();
              void connectMutation
                .mutateAsync(provider.provider)
                .then((result) => openConnectUrl(result.url, connectWindow))
                .catch(() => closeConnectWindow(connectWindow));
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
        )}
      </ItemActions>
    </Item>
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
      ) : (
        <div className="flex w-full flex-col gap-4">
          {providers.map((provider) => (
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
