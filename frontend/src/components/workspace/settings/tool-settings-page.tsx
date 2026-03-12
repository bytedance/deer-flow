"use client";

import { ChevronDownIcon, ChevronRightIcon } from "lucide-react";
import { useState } from "react";

import { Switch } from "@/components/ui/switch";
import { useI18n } from "@/core/i18n/hooks";
import {
  useEnableMCPServer,
  useMCPConfig,
  useMCPServerTools,
  useToggleMCPTool,
} from "@/core/mcp/hooks";
import type { MCPServerConfig, MCPServerToolsResult } from "@/core/mcp/types";
import { env } from "@/env";
import { cn } from "@/lib/utils";

import { SettingsSection } from "./settings-section";

export function ToolSettingsPage() {
  const { t } = useI18n();
  const { config, isLoading, error } = useMCPConfig();
  return (
    <SettingsSection
      title={t.settings.tools.title}
      description={t.settings.tools.description}
    >
      {isLoading ? (
        <div className="text-muted-foreground text-sm">{t.common.loading}</div>
      ) : error ? (
        <div>Error: {error.message}</div>
      ) : (
        config && <MCPServerList servers={config.mcp_servers} />
      )}
    </SettingsSection>
  );
}

function MCPServerList({
  servers,
}: {
  servers: Record<string, MCPServerConfig>;
}) {
  const { mutate: enableMCPServer } = useEnableMCPServer();
  const { toolsData, isLoading: toolsLoading, refetch: refetchTools } =
    useMCPServerTools();

  return (
    <div className="flex w-full flex-col gap-3">
      {Object.entries(servers).map(([name, config]) => {
        const serverTools = toolsData?.servers[name] ?? null;
        return (
          <MCPServerItem
            key={name}
            name={name}
            config={config}
            serverTools={serverTools}
            toolsLoading={toolsLoading}
            onToggleServer={(checked) =>
              enableMCPServer(
                { serverName: name, enabled: checked },
                { onSuccess: () => { if (checked) void refetchTools(); } },
              )
            }
          />
        );
      })}
    </div>
  );
}

function MCPServerItem({
  name,
  config,
  serverTools,
  toolsLoading,
  onToggleServer,
}: {
  name: string;
  config: MCPServerConfig;
  serverTools: MCPServerToolsResult | null;
  toolsLoading: boolean;
  onToggleServer: (checked: boolean) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const { t } = useI18n();
  const { mutate: toggleTool } = useToggleMCPTool();
  const isStaticOnly = env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true";
  const disabledTools = (config.disabled_tools as string[]) ?? [];

  return (
    <div className="border-border rounded-md border p-4">
      {/* Header row: always stays at top, switch pinned to top-right */}
      <div className="flex items-start justify-between gap-3">
        {/* Left: chevron + name + description */}
        <button
          className="flex min-w-0 flex-1 cursor-pointer items-start gap-2 text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
          onClick={() => setExpanded((v) => !v)}
          type="button"
          aria-expanded={expanded}
        >
          {expanded ? (
            <ChevronDownIcon className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
          ) : (
            <ChevronRightIcon className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
          )}
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium leading-snug">{name}</p>
            {config.description && (
              <p className="text-muted-foreground mt-0.5 line-clamp-2 text-sm leading-normal">
                {config.description}
              </p>
            )}
          </div>
        </button>

        {/* Right: server-level switch, always top-aligned */}
        <Switch
          className="shrink-0"
          checked={config.enabled}
          disabled={isStaticOnly}
          onCheckedChange={onToggleServer}
        />
      </div>

      {/* Collapsible tools panel */}
      {expanded && (
        <div className="mt-3 border-t pt-3">
          {!config.enabled ? null : toolsLoading ? (
            <p className="text-muted-foreground text-xs">
              {t.settings.tools.loadingTools}
            </p>
          ) : serverTools?.error ? (
            <p className="text-destructive text-xs">
              {t.settings.tools.loadToolsError}: {serverTools.error}
            </p>
          ) : !serverTools || serverTools.tools.length === 0 ? (
            <p className="text-muted-foreground text-xs">
              {t.settings.tools.noTools}
            </p>
          ) : (
            <div className="flex flex-col gap-1">
              {serverTools.tools.map((tool) => {
                const isEnabled = !disabledTools.includes(tool.name);
                return (
                  <div
                    key={tool.name}
                    className={cn(
                      "flex items-start justify-between gap-3 rounded-sm px-2 py-2",
                      "hover:bg-muted/50 transition-colors",
                    )}
                  >
                    <div className="min-w-0 flex-1">
                      <p
                        className={cn(
                          "truncate text-xs font-medium",
                          !isEnabled && "text-muted-foreground line-through",
                        )}
                      >
                        {tool.name}
                      </p>
                      {tool.description && (
                        <p className="text-muted-foreground line-clamp-2 text-xs">
                          {tool.description}
                        </p>
                      )}
                    </div>
                    <Switch
                      className="mt-0.5 shrink-0 scale-90"
                      checked={isEnabled}
                      disabled={isStaticOnly}
                      onCheckedChange={(checked) =>
                        toggleTool({
                          serverName: name,
                          toolName: tool.name,
                          enabled: checked,
                        })
                      }
                    />
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
