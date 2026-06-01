"use client";

import { useState } from "react";

import {
  Item,
  ItemActions,
  ItemContent,
  ItemDescription,
  ItemTitle,
} from "@/components/ui/item";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useI18n } from "@/core/i18n/hooks";
import { useMCPConfig, useEnableMCPServer } from "@/core/mcp/hooks";
import type { MCPServerConfig } from "@/core/mcp/types";
import { env } from "@/env";

import CapabilitiesPage from "@/app/workspace/capabilities/page";
import { CapabilityDetailView } from "./capability-detail-view";
import { A2UIDebugPanel } from "@/components/debug/A2UIDebugPanel";

export function ToolSettingsPage() {
  const { t } = useI18n();
  const { config, isLoading, error } = useMCPConfig();
  const [selectedCap, setSelectedCap] = useState<{
    type: string;
    name: string;
  } | null>(null);

  return (
    <Tabs defaultValue="management" className="w-full">
      <TabsList>
        <TabsTrigger value="management">
          {t.settings.tools.tabs.toolManagement}
        </TabsTrigger>
        <TabsTrigger value="capabilities">
          {t.settings.tools.tabs.capabilities}
        </TabsTrigger>
        <TabsTrigger value="a2ui-debug">
          {t.settings.tools.tabs.a2uiDebug}
        </TabsTrigger>
      </TabsList>

      <TabsContent value="management">
        <div className="space-y-4 pt-2">
          {isLoading ? (
            <div className="text-muted-foreground text-sm">
              {t.common.loading}
            </div>
          ) : error ? (
            <div>Error: {error.message}</div>
          ) : (
            config && <MCPServerList servers={config.mcp_servers} />
          )}
        </div>
      </TabsContent>

      <TabsContent value="capabilities">
        <div className="pt-2">
          {selectedCap ? (
            <CapabilityDetailView
              capType={selectedCap.type}
              capName={selectedCap.name}
              onBack={() => setSelectedCap(null)}
            />
          ) : (
            <CapabilitiesPage
              onSelectDetail={(type, name) =>
                setSelectedCap({ type, name })
              }
            />
          )}
        </div>
      </TabsContent>

      <TabsContent value="a2ui-debug">
        <div className="pt-2" style={{ minHeight: "50vh" }}>
          <A2UIDebugPanel />
        </div>
      </TabsContent>
    </Tabs>
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
