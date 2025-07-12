// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { motion } from "framer-motion";
import { Blocks, PencilRuler, Trash } from "lucide-react";
import { useTranslations } from "next-intl";
import { useCallback, useState } from "react";

import { Tooltip } from "~/components/deer-flow/tooltip";
import { Button } from "~/components/ui/button";
import { Switch } from "~/components/ui/switch";
import type { MCPServerMetadata } from "~/core/mcp";
import { cn } from "~/lib/utils";

import { AddMCPServerDialog } from "../dialogs/add-mcp-server-dialog";

import type { Tab } from "./types";

export const MCPTab: Tab = ({ settings, onChange }) => {
  const t = useTranslations("settings.mcp");
  const [servers, setServers] = useState<MCPServerMetadata[]>(
    settings.mcp.servers,
  );
  const [newlyAdded, setNewlyAdded] = useState(false);
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
  const handleToggleServer = useCallback(
    (name: string, enabled: boolean) => {
      const merged = settings.mcp.servers.map((server) =>
        server.name === name ? { ...server, enabled } : server,
      );
      setServers(merged);
      onChange({ ...settings, mcp: { ...settings.mcp, servers: merged } });
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
                          handleToggleServer(server.name, checked);
                        }}
                      />
                    </div>
                  </Tooltip>
                </div>
                <div className="absolute top-1 right-12 opacity-0 transition-opacity duration-300 group-hover:opacity-100">
                  <Tooltip title={t("deleteServer")}>
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => handleDeleteServer(server.name)}
                    >
                      <Trash />
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
