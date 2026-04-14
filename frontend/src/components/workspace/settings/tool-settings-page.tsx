"use client";

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
import type { MCPServerConfig, MCPToolConfig } from "@/core/mcp/types";
import { env } from "@/env";

import { SettingsSection } from "./settings-section";

export function ToolSettingsPage() {
  const { t } = useI18n();
  const { config, isLoading, error } = useMCPConfig();
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
  const { t } = useI18n();
  const { mutate: enableMCPServer } = useEnableMCPServer();
  const { mutate: enableMCPTool } = useEnableMCPTool();

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
                    disabled={env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true"}
                    onCheckedChange={(checked) =>
                      enableMCPServer({ serverName: name, enabled: checked })
                    }
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
                        disabled={env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true"}
                        onCheckedChange={(checked) =>
                          enableMCPTool({
                            serverName: name,
                            toolName,
                            enabled: checked,
                          })
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
