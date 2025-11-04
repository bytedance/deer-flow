// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { motion } from "framer-motion";
import { Blocks, Edit2, PencilRuler, RefreshCw, Trash } from "lucide-react";
import { useTranslations } from "next-intl";
import { useCallback, useState } from "react";

import { Tooltip } from "~/components/deer-flow/tooltip";
import { Button } from "~/components/ui/button";
import { Switch } from "~/components/ui/switch";
import { queryMCPServerMetadata } from "~/core/api";
import type { MCPServerMetadata } from "~/core/mcp";
import { cn } from "~/lib/utils";

import { AddMCPServerDialog } from "../dialogs/add-mcp-server-dialog";
import { EditMCPServerDialog } from "../dialogs/edit-mcp-server-dialog";

import type { Tab } from "./types";

export const MCPTab: Tab = ({ settings, onChange }) => {
  const t = useTranslations("settings.mcp");
  const [servers, setServers] = useState<MCPServerMetadata[]>(
    settings.mcp.servers,
  );
  const [newlyAdded, setNewlyAdded] = useState(false);
  const [editingServer, setEditingServer] = useState<MCPServerMetadata | null>(null);
  const handleAddServers = useCallback(
    (servers: MCPServerMetadata[]) => {
      const merged = mergeServers(settings.mcp.servers, servers);
      setServers(merged);
      onChange({ ...settings, mcp: { ...settings.mcp, servers: merged } });
      setNewlyAdded(true);
      setTimeout(() => {
        setNewlyAdded(false);
      }, 1000);
      setTimeout(() => {
        document.getElementById("settings-content-scrollable")?.scrollTo({
          top: 0,
          behavior: "smooth",
        });
      }, 100);
    },
    [onChange, settings],
  );
  const handleDeleteServer = useCallback(
    (name: string) => {
      const merged = settings.mcp.servers.filter(
        (server) => server.name !== name,
      );
      setServers(merged);
      onChange({ ...settings, mcp: { ...settings.mcp, servers: merged } });
    },
    [onChange, settings],
  );

  const handleEditServer = useCallback(async (config: string) => {
    if (!editingServer) return false;

    try {
      const parsedConfig = JSON.parse(config) as { mcpServers?: Record<string, MCPServerMetadata> };

      if (!parsedConfig.mcpServers || typeof parsedConfig.mcpServers !== 'object') {
        console.error('Invalid configuration format: mcpServers not found');
        return false;
      }

      const serverEntries = Object.entries(parsedConfig.mcpServers);
      if (serverEntries.length === 0) {
        console.error('No server configuration found in mcpServers');
        return false;
      }

      const firstEntry = serverEntries[0];
      if (!firstEntry) {
        console.error('Failed to get server configuration');
        return false;
      }

      const [serverName, serverConfig] = firstEntry;

      // Update the server configuration
      const updatedServers = settings.mcp.servers.map(server =>
        server.name === editingServer.name
          ? {
            ...server,
            ...serverConfig,
            name: serverName, // Allow renaming the server
            updatedAt: Date.now(),
          }
          : server
      );

      setServers(updatedServers);
      onChange({ ...settings, mcp: { ...settings.mcp, servers: updatedServers } });
      return true;
    } catch (error) {
      console.error('Failed to update server configuration:', error);
      return false;
    }
  }, [editingServer, onChange, settings]);

  const handleRefreshServers = useCallback(async (serverName?: string) => {
    try {
      // Create a new array with the updated server
      const updatedServers = await Promise.all(
        settings.mcp.servers.map(async (server) => {
          // Skip if this is not the server we want to refresh
          if (serverName && server.name !== serverName) {
            return server;
          }
          
          // Skip disabled servers unless explicitly requested
          if (!server.enabled && server.name !== serverName) {
            return server;
          }

          try {
            // Get the latest metadata
            const metadata = await queryMCPServerMetadata(server);
            
            // Create a new server object with preserved properties
            return {
              ...server, // Keep all existing properties
              ...metadata, // Apply metadata updates
              name: server.name, // Ensure name is preserved
              enabled: server.enabled, // Preserve the enabled state
              createdAt: server.createdAt, // Keep the original creation time
              updatedAt: Date.now(), // Update the last updated time
            };
          } catch (error) {
            console.error(`Failed to refresh server ${server.name}:`, error);
            // Return the original server if refresh fails
            return server;
          }
        })
      );

      // Update the servers list
      setServers(updatedServers);
      onChange({ ...settings, mcp: { ...settings.mcp, servers: updatedServers } });
    } catch (error) {
      console.error('Failed to refresh MCP servers:', error);
    }
  }, [onChange, settings]);

  const handleToggleServer = useCallback(
    async (name: string, enabled: boolean) => {
      const merged = settings.mcp.servers.map((server) =>
        server.name === name ? { ...server, enabled } : server,
      );
      setServers(merged);
      onChange({ ...settings, mcp: { ...settings.mcp, servers: merged } });

      // Refresh server metadata when enabling a server
      if (enabled) {
        try {
          const server = merged.find(s => s.name === name);
          if (server) {
            const metadata = await queryMCPServerMetadata(server);
            const updatedServers = merged.map(s =>
              s.name === name ? { ...metadata, enabled: true } : s
            );
            setServers(updatedServers);
            onChange({ ...settings, mcp: { ...settings.mcp, servers: updatedServers } });
          }
        } catch (error) {
          console.error(`Failed to refresh server ${name}:`, error);
        }
      }
    },
    [onChange, settings],
  );

  const animationProps = {
    initial: { backgroundColor: "gray" },
    animate: { backgroundColor: "transparent" },
    transition: { duration: 1 },
    style: {
      transition: "background-color 1s ease-out",
    },
  };
  return (
    <div className="flex flex-col gap-4">
      <header>
        <div className="flex items-center justify-between gap-2">
          <h1 className="text-lg font-medium">{t("title")}</h1>
          <AddMCPServerDialog onAdd={handleAddServers} />
        </div>
        <div className="text-muted-foreground markdown text-sm">
          {t("description")}
          <a
            className="ml-1"
            target="_blank"
            href="https://modelcontextprotocol.io/"
          >
            {t("learnMore")}
          </a>
        </div>
      </header>
      <main>
        <ul id="mcp-servers-list" className="flex flex-col gap-4">
          {servers.map((server) => {
            const isNew =
              server.createdAt &&
              server.createdAt > Date.now() - 1000 * 60 * 60 * 1;
            return (
              <motion.li
                className={
                  "!bg-card group relative overflow-hidden rounded-lg border pb-2 shadow duration-300"
                }
                key={server.name}
                {...(isNew && newlyAdded && animationProps)}
              >
                <div className="absolute top-3 right-2">
                  <Tooltip title={t("enableDisable")}>
                    <div className="flex items-center gap-2">
                      <Switch
                        id="airplane-mode"
                        checked={server.enabled}
                        onCheckedChange={(checked) => {
                          void handleToggleServer(server.name, checked);
                        }}
                      />
                    </div>
                  </Tooltip>
                </div>
                <div className="absolute top-1 right-12 flex gap-1 opacity-0 transition-opacity duration-300 group-hover:opacity-100">
                  <Tooltip title={t("editServer")}>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8"
                      onClick={(e) => {
                        e.stopPropagation();
                        setEditingServer(server);
                      }}
                    >
                      <Edit2 className="h-4 w-4" />
                    </Button>
                  </Tooltip>
                  <Tooltip title={t("refreshServer")}>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8"
                      onClick={(e) => {
                        e.stopPropagation();
                        void handleRefreshServers(server.name);
                      }}
                    >
                      <RefreshCw className="h-4 w-4" />
                    </Button>
                  </Tooltip>
                  <Tooltip title={t("deleteServer")}>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8"
                      onClick={(e) => {
                        e.stopPropagation();
                        handleDeleteServer(server.name);
                      }}
                    >
                      <Trash className="h-4 w-4" />
                    </Button>
                  </Tooltip>
                </div>
                <div
                  className={cn(
                    "flex flex-col items-start px-4 py-2",
                    !server.enabled && "text-muted-foreground",
                  )}
                >
                  <div
                    className={cn(
                      "mb-2 flex items-center gap-2",
                      !server.enabled && "opacity-70",
                    )}
                  >
                    <div className="text-lg font-medium">{server.name}</div>
                    {!server.enabled && (
                      <div className="bg-primary text-primary-foreground h-fit rounded px-1.5 py-0.5 text-xs">
                        {t("disabled")}
                      </div>
                    )}
                    <div className="bg-primary text-primary-foreground h-fit rounded px-1.5 py-0.5 text-xs">
                      {server.transport}
                    </div>
                    {isNew && (
                      <div className="bg-primary text-primary-foreground h-fit rounded px-1.5 py-0.5 text-xs">
                        {t("new")}
                      </div>
                    )}
                  </div>
                  <ul
                    className={cn(
                      "flex flex-wrap items-center gap-2",
                      !server.enabled && "opacity-70",
                    )}
                  >
                    <PencilRuler size={16} />
                    {server.tools.map((tool) => (
                      <li
                        key={tool.name}
                        className="text-muted-foreground border-muted-foreground w-fit rounded-md border px-2"
                      >
                        <Tooltip key={tool.name} title={tool.description}>
                          <div className="w-fit text-sm">{tool.name}</div>
                        </Tooltip>
                      </li>
                    ))}
                  </ul>
                </div>
              </motion.li>
            );
          })}
        </ul>
      </main>
      {editingServer && (
        <EditMCPServerDialog
          server={editingServer}
          open={!!editingServer}
          onOpenChange={(open) => !open && setEditingServer(null)}
          onSave={async (config) => {
            const success = await handleEditServer(config);
            if (success) {
              setEditingServer(null);
            }
            return success;
          }}
        />
      )}
    </div>
  );
};
MCPTab.icon = Blocks;
MCPTab.displayName = "MCP";
MCPTab.badge = "Beta";
MCPTab.displayName = "MCP";

function mergeServers(
  existing: MCPServerMetadata[],
  added: MCPServerMetadata[],
): MCPServerMetadata[] {
  const serverMap = new Map(existing.map((server) => [server.name, server]));

  for (const addedServer of added) {
    addedServer.createdAt = Date.now();
    addedServer.updatedAt = Date.now();
    serverMap.set(addedServer.name, addedServer);
  }

  const result = Array.from(serverMap.values());
  result.sort((a, b) => b.createdAt - a.createdAt);
  return result;
}
