"use client";
import { useEffect } from "react";
import { env } from "../../env";
import { changeSettings, useSettingsStore } from "../../core/store/settings-store";

export default function MCPConfigProvider({ children }: { children: React.ReactNode }) {
  useEffect(() => {
    const configPath = (env as Record<string, any>).NEXT_PUBLIC_MCP_CONFIG_PATH || "/mcp.json";
    fetch(configPath)
      .then((res) => res.json())
      .then((data) => {
        if (data.servers) {
          changeSettings({
            ...useSettingsStore.getState(),
            mcp: { servers: data.servers },
          });
        }
      })
      .catch(() => {});
  }, []);
  return <>{children}</>;
} 