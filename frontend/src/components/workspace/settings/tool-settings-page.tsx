"use client";

import { WrenchIcon } from "lucide-react";

import {
  Item,
  ItemActions,
  ItemContent,
  ItemDescription,
  ItemTitle,
} from "@/components/ui/item";
import { Switch } from "@/components/ui/switch";
import { useI18n } from "@/core/i18n/hooks";
import { useMCPConfig, useEnableMCPServer } from "@/core/mcp/hooks";
import { useConfiguredTools } from "@/core/tools/hooks";
import type { MCPServerConfig } from "@/core/mcp/types";
import { env } from "@/env";

import { SettingsSection } from "./settings-section";

function getToolDisplayName(tool: { name: string; name_zh?: string }, locale: string): string {
  return locale === "zh-CN" && tool.name_zh ? tool.name_zh : tool.name;
}

function getToolDisplayGroup(tool: { group: string; group_zh?: string }, locale: string): string {
  return locale === "zh-CN" && tool.group_zh ? tool.group_zh : tool.group;
}

function getToolDisplayDescription(tool: { description: string; description_zh?: string }, locale: string): string {
  return locale === "zh-CN" && tool.description_zh ? tool.description_zh : tool.description;
}

export function ToolSettingsPage() {
  const { t, locale } = useI18n();
  const { config: mcpConfig, isLoading: isLoadingMCP, error: errorMCP } = useMCPConfig();
  const { tools: builtInTools, isLoading: isLoadingTools, error: errorTools } = useConfiguredTools();

  const isLoading = isLoadingMCP || isLoadingTools;
  const error = errorMCP || errorTools;

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
        <div className="flex flex-col gap-6">
          {/* Built-in Tools Section */}
          {builtInTools.length > 0 && (
            <div>
              <h3 className="text-sm font-medium mb-3 flex items-center gap-2">
                <WrenchIcon className="size-4" />
                {t.settings.tools.builtInTools || "内置工具"}
              </h3>
              <div className="flex flex-col gap-3">
                {builtInTools.map((tool) => (
                  <Item className="w-full" variant="outline" key={tool.name}>
                    <ItemContent>
                      <ItemTitle>
                        <div className="flex items-center gap-2">
                          <span className="font-medium">{getToolDisplayName(tool, locale)}</span>
                          <span className="text-xs text-muted-foreground bg-muted px-2 py-0.5 rounded">
                            {getToolDisplayGroup(tool, locale)}
                          </span>
                        </div>
                      </ItemTitle>
                      {getToolDisplayDescription(tool, locale) && (
                        <ItemDescription className="line-clamp-2">
                          {getToolDisplayDescription(tool, locale)}
                        </ItemDescription>
                      )}
                    </ItemContent>
                  </Item>
                ))}
              </div>
            </div>
          )}

          {/* MCP Servers Section */}
          {mcpConfig && Object.keys(mcpConfig.mcp_servers).length > 0 && (
            <div>
              <h3 className="text-sm font-medium mb-3">
                {t.settings.tools.mcpServers || "MCP 服务器"}
              </h3>
              <MCPServerList servers={mcpConfig.mcp_servers} />
            </div>
          )}
        </div>
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
  return (
    <div className="flex w-full flex-col gap-4">
      {Object.entries(servers).map(([name, config]) => (
        <Item className="w-full" variant="outline" key={name}>
          <ItemContent>
            <ItemTitle>
              <div className="flex items-center gap-2">
                <div>{name}</div>
              </div>
            </ItemTitle>
            <ItemDescription className="line-clamp-4">
              {config.description}
            </ItemDescription>
          </ItemContent>
          <ItemActions>
            <Switch
              checked={config.enabled}
              disabled={env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true"}
              onCheckedChange={(checked) =>
                enableMCPServer({ serverName: name, enabled: checked })
              }
            />
          </ItemActions>
        </Item>
      ))}
    </div>
  );
}
