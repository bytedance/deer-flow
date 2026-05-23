"use client";

import {
  CheckCircle2Icon,
  Loader2Icon,
  PlusIcon,
  Trash2Icon,
  XCircleIcon,
  ZapIcon,
} from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Item,
  ItemActions,
  ItemContent,
  ItemDescription,
  ItemTitle,
} from "@/components/ui/item";
import { Switch } from "@/components/ui/switch";
import { useI18n } from "@/core/i18n/hooks";
import {
  useEnableMCPServer,
  useMCPConfig,
  useRemoveMCPServer,
  useTestMCPServer,
} from "@/core/mcp/hooks";
import type { MCPServerConfig } from "@/core/mcp/types";
import { env } from "@/env";

import { SettingsSection } from "./settings-section";
import { ToolCatalogModal } from "./tool-catalog-modal";

type TestState =
  | { status: "idle" }
  | { status: "pending" }
  | { status: "ok"; toolCount: number; toolNames: string[] }
  | { status: "error"; message: string };

export function ToolSettingsPage() {
  const { t } = useI18n();
  const { config, isLoading, error } = useMCPConfig();
  const [catalogOpen, setCatalogOpen] = useState(false);
  const readOnly = env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true";

  return (
    <SettingsSection
      title={t.settings.tools.title}
      description={t.settings.tools.description}
    >
      <div className="flex flex-col gap-4">
        {!readOnly && (
          <div className="flex justify-end">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => setCatalogOpen(true)}
            >
              <PlusIcon />
              Add Tool
            </Button>
          </div>
        )}
        {isLoading ? (
          <div className="text-muted-foreground text-sm">
            {t.common.loading}
          </div>
        ) : error ? (
          <div>Error: {error.message}</div>
        ) : (
          config && (
            <MCPServerList servers={config.mcp_servers} readOnly={readOnly} />
          )
        )}
      </div>
      <ToolCatalogModal open={catalogOpen} onOpenChange={setCatalogOpen} />
    </SettingsSection>
  );
}

function MCPServerList({
  servers,
  readOnly,
}: {
  servers: Record<string, MCPServerConfig>;
  readOnly: boolean;
}) {
  const { mutate: enableMCPServer } = useEnableMCPServer();
  const { mutate: removeMCPServer } = useRemoveMCPServer();
  const testMutation = useTestMCPServer();
  const [testStates, setTestStates] = useState<Record<string, TestState>>({});

  const entries = Object.entries(servers);
  if (entries.length === 0) {
    return (
      <div className="text-muted-foreground rounded-md border border-dashed p-6 text-center text-sm">
        No MCP tools connected yet. Click &ldquo;Add Tool&rdquo; to connect one.
      </div>
    );
  }

  async function handleTest(name: string) {
    setTestStates((prev) => ({ ...prev, [name]: { status: "pending" } }));
    try {
      const result = await testMutation.mutateAsync(name);
      setTestStates((prev) => ({
        ...prev,
        [name]: result.ok
          ? {
              status: "ok",
              toolCount: result.tool_count ?? 0,
              toolNames: result.tool_names,
            }
          : {
              status: "error",
              message: result.error ?? "Test failed",
            },
      }));
    } catch (error) {
      setTestStates((prev) => ({
        ...prev,
        [name]: {
          status: "error",
          message: error instanceof Error ? error.message : "Test failed",
        },
      }));
    }
  }

  return (
    <div className="flex w-full flex-col gap-4">
      {entries.map(([name, config]) => {
        const state = testStates[name] ?? { status: "idle" as const };
        return (
          <Item className="w-full" variant="outline" key={name}>
            <ItemContent>
              <ItemTitle>
                <div className="flex items-center gap-2">
                  <div>{name}</div>
                  {state.status === "ok" && (
                    <span className="inline-flex items-center gap-1 text-xs text-green-600">
                      <CheckCircle2Icon className="size-3" />
                      {state.toolCount} tools
                    </span>
                  )}
                  {state.status === "error" && (
                    <span className="text-destructive inline-flex items-center gap-1 text-xs">
                      <XCircleIcon className="size-3" />
                      Test failed
                    </span>
                  )}
                </div>
              </ItemTitle>
              <ItemDescription className="line-clamp-4">
                {state.status === "error"
                  ? state.message
                  : state.status === "ok" && state.toolNames.length > 0
                    ? `Tools: ${state.toolNames.join(", ")}`
                    : config.description}
              </ItemDescription>
            </ItemContent>
            <ItemActions>
              {!readOnly && (
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-sm"
                  aria-label={`Test ${name}`}
                  disabled={state.status === "pending"}
                  onClick={() => {
                    void handleTest(name);
                  }}
                >
                  {state.status === "pending" ? (
                    <Loader2Icon className="animate-spin" />
                  ) : (
                    <ZapIcon />
                  )}
                </Button>
              )}
              <Switch
                checked={config.enabled}
                disabled={readOnly}
                onCheckedChange={(checked) =>
                  enableMCPServer({ serverName: name, enabled: checked })
                }
              />
              {!readOnly && (
                <Button
                  type="button"
                  variant="ghost"
                  size="icon-sm"
                  aria-label={`Remove ${name}`}
                  onClick={() => {
                    if (window.confirm(`Remove MCP server "${name}"?`)) {
                      removeMCPServer({ serverName: name });
                    }
                  }}
                >
                  <Trash2Icon />
                </Button>
              )}
            </ItemActions>
          </Item>
        );
      })}
    </div>
  );
}
