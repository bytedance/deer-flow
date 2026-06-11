"use client";

import { CheckIcon, LoaderCircleIcon } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  SidebarGroup,
  SidebarGroupLabel,
  SidebarMenu,
  SidebarMenuItem,
  useSidebar,
} from "@/components/ui/sidebar";
import { Skeleton } from "@/components/ui/skeleton";
import {
  useChannelProviders,
  useConnectChannelProvider,
} from "@/core/channels/hooks";
import {
  closeConnectWindow,
  openConnectUrl,
  prepareConnectWindow,
} from "@/core/channels/open-connect-url";
import type { ChannelProvider } from "@/core/channels/types";
import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

import { ChannelProviderIcon } from "./channel-provider-icon";

function providerCanConnect(provider: ChannelProvider): boolean {
  return (
    (provider.connectable ?? (provider.enabled && provider.configured)) &&
    provider.connection_status !== "connected"
  );
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

export function WorkspaceChannelsList() {
  const { open: isSidebarOpen } = useSidebar();
  const { t } = useI18n();
  const { enabled, providers, isLoading, error } = useChannelProviders();
  const connectMutation = useConnectChannelProvider();

  if (!isSidebarOpen) {
    return null;
  }

  if (isLoading) {
    return (
      <SidebarGroup className="pt-0">
        <SidebarGroupLabel>{t.sidebar.channels}</SidebarGroupLabel>
        <div className="space-y-2 px-2 py-1">
          <Skeleton className="h-8 w-full" />
          <Skeleton className="h-8 w-full" />
          <Skeleton className="h-8 w-full" />
        </div>
      </SidebarGroup>
    );
  }

  if (error || !enabled || providers.length === 0) {
    return null;
  }

  return (
    <SidebarGroup className="pt-0">
      <SidebarGroupLabel>{t.sidebar.channels}</SidebarGroupLabel>
      <SidebarMenu>
        {providers.map((provider) => {
          const isConnected = provider.connection_status === "connected";
          const isPending =
            connectMutation.isPending &&
            connectMutation.variables === provider.provider;
          const canConnect = providerCanConnect(provider);
          const unavailableReason = getProviderUnavailableReason(provider, t);

          return (
            <SidebarMenuItem key={provider.provider}>
              <div className="hover:bg-sidebar-accent flex h-10 items-center gap-2 rounded-md px-2 transition-colors">
                <ChannelProviderIcon
                  provider={provider.provider}
                  className="size-5 shrink-0"
                />
                <span className="min-w-0 flex-1 truncate text-sm font-medium">
                  {provider.display_name}
                </span>
                <Button
                  type="button"
                  size="sm"
                  variant={isConnected ? "outline" : "secondary"}
                  className={cn(
                    "h-8 w-24 px-2 text-xs",
                    isConnected && "gap-1",
                  )}
                  disabled={isConnected || isPending}
                  title={unavailableReason}
                  onClick={() => {
                    if (!canConnect) {
                      toast.error(unavailableReason ?? t.channels.unavailable);
                      return;
                    }

                    const connectWindow =
                      provider.auth_mode === "deep_link"
                        ? prepareConnectWindow()
                        : null;
                    void connectMutation
                      .mutateAsync(provider.provider)
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
                          error instanceof Error
                            ? error.message
                            : t.channels.unavailable,
                        );
                      });
                  }}
                >
                  {isPending ? (
                    <LoaderCircleIcon className="size-3.5 animate-spin" />
                  ) : isConnected ? (
                    <CheckIcon className="size-3.5" />
                  ) : null}
                  <span>
                    {isConnected ? t.channels.connected : t.channels.connect}
                  </span>
                </Button>
              </div>
            </SidebarMenuItem>
          );
        })}
      </SidebarMenu>
    </SidebarGroup>
  );
}
