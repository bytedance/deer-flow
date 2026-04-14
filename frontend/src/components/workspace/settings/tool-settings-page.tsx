"use client";

import {
  CircleCheckIcon,
  Loader2Icon,
  TriangleAlertIcon,
} from "lucide-react";

import {
  Alert,
  AlertDescription,
  AlertTitle,
} from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import {
  Item,
  ItemActions,
  ItemContent,
  ItemDescription,
  ItemGroup,
  ItemSeparator,
  ItemTitle,
} from "@/components/ui/item";
import { Switch } from "@/components/ui/switch";
import { useI18n } from "@/core/i18n/hooks";
import {
  useEnableMCPServer,
  useEnableMCPTool,
  useMCPConfig,
} from "@/core/mcp/hooks";
import type {
  MCPRuntimeConfig,
  MCPServerConfig,
  MCPToolConfig,
} from "@/core/mcp/types";
import { formatTimeAgo } from "@/core/utils/datetime";
import { env } from "@/env";

import { SettingsSection } from "./settings-section";

export function ToolSettingsPage() {
  const { t } = useI18n();
  const { config, isLoading, error } = useMCPConfig();
  const enableServerMutation = useEnableMCPServer();
  const enableToolMutation = useEnableMCPTool();
  const isSaving =
    enableServerMutation.isPending || enableToolMutation.isPending;
  const rawSaveError = enableServerMutation.error ?? enableToolMutation.error;
  const saveError =
    rawSaveError instanceof Error ? rawSaveError : rawSaveError ? new Error(String(rawSaveError)) : null;

  return (
    <SettingsSection
      title={t.settings.tools.title}
      description={t.settings.tools.description}
    >
      <p className="text-muted-foreground text-sm">
        {t.settings.tools.applyChangesHint}
      </p>
      {isLoading ? (
        <div className="text-muted-foreground text-sm">{t.common.loading}</div>
      ) : error ? (
        <div>Error: {error.message}</div>
      ) : (
        config && (
          <div className="space-y-4">
            <MCPRuntimeStatusAlert
              isSaving={isSaving}
              runtime={config.runtime}
              saveError={saveError}
            />
            <MCPServerList
              disableInteractions={
                env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true" || isSaving
              }
              onToggleServer={(serverName, enabled) =>
                enableServerMutation.mutate({ serverName, enabled })
              }
              onToggleTool={(serverName, toolName, enabled) =>
                enableToolMutation.mutate({ serverName, toolName, enabled })
              }
              servers={config.mcp_servers}
            />
          </div>
        )
      )}
    </SettingsSection>
  );
}

function MCPRuntimeStatusAlert({
  isSaving,
  runtime,
  saveError,
}: {
  isSaving: boolean;
  runtime: MCPRuntimeConfig;
  saveError: Error | null;
}) {
  const { t } = useI18n();

  if (saveError) {
    return (
      <Alert variant="destructive">
        <TriangleAlertIcon />
        <AlertTitle>{t.settings.tools.saveFailedTitle}</AlertTitle>
        <AlertDescription>{saveError.message}</AlertDescription>
      </Alert>
    );
  }

  const Icon = isSaving
    ? Loader2Icon
    : runtime.status === "pending_reload"
      ? TriangleAlertIcon
      : CircleCheckIcon;

  const statusLabel = isSaving
    ? t.settings.tools.statusSaving
    : runtime.status === "pending_reload"
      ? t.settings.tools.statusPendingReload
      : runtime.status === "in_sync"
        ? t.settings.tools.statusInSync
        : t.settings.tools.statusNotInitialized;

  const statusDescription = isSaving
    ? t.settings.tools.savingDescription
    : runtime.status === "pending_reload"
      ? t.settings.tools.pendingReloadDescription
      : runtime.status === "in_sync"
        ? t.settings.tools.inSyncDescription
        : t.settings.tools.notInitializedDescription;

  const configSavedAt = runtime.config_last_modified_at
    ? t.settings.tools.configSavedAt(
        formatTimeAgo(runtime.config_last_modified_at),
      )
    : t.settings.tools.configNotSavedYet;

  const runtimeLoadedAt = runtime.runtime_config_last_loaded_at
    ? t.settings.tools.runtimeLoadedAt(
        formatTimeAgo(runtime.runtime_config_last_loaded_at),
      )
    : null;

  const runtimeSummary = runtime.cache_initialized
    ? runtime.active_tool_count > 0
      ? t.settings.tools.runtimeSummary(
          runtime.active_tool_count,
          runtime.active_server_count,
        )
      : t.settings.tools.runtimeEmpty
    : null;

  return (
    <Alert>
      <Icon className={isSaving ? "animate-spin" : undefined} />
      <AlertTitle className="flex flex-wrap items-center gap-2">
        {t.settings.tools.runtimeStatusTitle}
        <Badge
          variant={
            runtime.status === "pending_reload" && !isSaving
              ? "outline"
              : "secondary"
          }
        >
          {statusLabel}
        </Badge>
        <Badge variant="outline">{t.settings.tools.noRestartRequired}</Badge>
      </AlertTitle>
      <AlertDescription>
        <p>{statusDescription}</p>
        <p>{configSavedAt}</p>
        {runtimeLoadedAt ? <p>{runtimeLoadedAt}</p> : null}
        {runtimeSummary ? <p>{runtimeSummary}</p> : null}
        <p>{t.settings.tools.reloadModeNextLoad}</p>
      </AlertDescription>
    </Alert>
  );
}

function MCPServerList({
  disableInteractions,
  onToggleServer,
  onToggleTool,
  servers,
}: {
  disableInteractions: boolean;
  onToggleServer: (serverName: string, enabled: boolean) => void;
  onToggleTool: (
    serverName: string,
    toolName: string,
    enabled: boolean,
  ) => void;
  servers: Record<string, MCPServerConfig>;
}) {
  const { t } = useI18n();

  return (
    <ItemGroup className="w-full gap-4">
      {Object.entries(servers)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([name, config]) => {
          const tools = Object.entries(config.tools ?? {}).sort(([left], [right]) =>
            left.localeCompare(right),
          );

          return (
            <Item className="w-full flex-col items-stretch" variant="outline" key={name}>
              <div className="flex items-start justify-between gap-4">
                <ItemContent>
                  <ItemTitle className="w-full justify-between">
                    <div className="min-w-0">
                      <div>{name}</div>
                      <div className="text-muted-foreground text-xs font-normal">
                        {t.settings.tools.toolCount(tools.length)}
                      </div>
                    </div>
                  </ItemTitle>
                  <ItemDescription className="line-clamp-4">
                    {config.description || t.settings.tools.noDescription}
                  </ItemDescription>
                </ItemContent>
                <ItemActions>
                  <Switch
                    checked={config.enabled}
                    disabled={disableInteractions}
                    onCheckedChange={(checked) => onToggleServer(name, checked)}
                  />
                </ItemActions>
              </div>
              <ItemSeparator />
              {tools.length > 0 ? (
                <div className="flex flex-col gap-2">
                  {tools.map(([toolName, toolConfig], index) => (
                    <div key={toolName}>
                      {index > 0 && <ItemSeparator />}
                      <MCPToolRow
                        disabled={disableInteractions}
                        onCheckedChange={(checked) =>
                          onToggleTool(name, toolName, checked)
                        }
                        toolConfig={toolConfig}
                        toolName={toolName}
                      />
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-muted-foreground text-sm">
                  {config.enabled
                    ? t.settings.tools.noToolsDiscovered
                    : t.settings.tools.enableServerToRefresh}
                </div>
              )}
            </Item>
          );
        })}
    </ItemGroup>
  );
}

function MCPToolRow({
  disabled,
  onCheckedChange,
  toolConfig,
  toolName,
}: {
  disabled: boolean;
  onCheckedChange: (checked: boolean) => void;
  toolConfig: MCPToolConfig;
  toolName: string;
}) {
  const { t } = useI18n();

  return (
    <Item className="px-0 py-2" size="sm">
      <ItemContent>
        <ItemTitle>{toolName}</ItemTitle>
        <ItemDescription>
          {toolConfig.description ||
            (toolConfig.discovered
              ? t.settings.tools.discoveredTool
              : t.settings.tools.configuredTool)}
        </ItemDescription>
      </ItemContent>
      <ItemActions>
        <Switch
          checked={toolConfig.enabled}
          disabled={disabled}
          onCheckedChange={onCheckedChange}
        />
      </ItemActions>
    </Item>
  );
}
