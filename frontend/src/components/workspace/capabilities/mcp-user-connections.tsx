"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { useI18n } from "@/core/i18n/hooks";
import {
  changeMCPUserConnection,
  loadMCPUserConnections,
} from "@/core/mcp/user-oauth";

export function MCPUserConnections({
  userId,
  query,
  callbackFailed,
}: {
  userId: string;
  query: string;
  callbackFailed: boolean;
}) {
  const { t } = useI18n();
  const copy = t.capabilities.mcpConnections;
  const client = useQueryClient();
  // Configuration changes already invalidate the MCP query family.
  const queryKey = ["mcpConfig", "user-oauth", userId];
  const connections = useQuery({
    queryKey,
    queryFn: ({ signal }) => loadMCPUserConnections(signal),
    retry: false,
  });
  const change = useMutation({
    mutationFn: ({
      serverKey,
      action,
    }: {
      serverKey: string;
      action: "connect" | "disconnect";
    }) => changeMCPUserConnection(serverKey, action),
    retry: false,
    onSuccess: async (authorizationUrl) => {
      if (!authorizationUrl) await client.invalidateQueries({ queryKey });
    },
  });
  const visible = (connections.data ?? []).filter((item) =>
    item.display_name.toLowerCase().includes(query.trim().toLowerCase()),
  );
  if (!visible.length && !connections.isError && !callbackFailed) return null;

  return (
    <section
      id="my-mcp-connections"
      aria-labelledby="my-mcp-connections-heading"
      className="space-y-3 rounded-lg border px-4 py-4"
    >
      <h3 id="my-mcp-connections-heading" className="text-base font-semibold">
        {copy.title}
      </h3>
      {(change.isError || callbackFailed) && (
        <p role="alert" className="text-destructive text-sm">
          {copy.actionFailed}
        </p>
      )}
      {connections.isError ? (
        <p role="alert" className="text-destructive text-sm">
          {copy.loadFailed}
        </p>
      ) : (
        <ul className="divide-y">
          {visible.map((item) => {
            const canDisconnect =
              item.status === "connected" || item.status === "removed";
            const actionLabel = canDisconnect
              ? copy.disconnect
              : item.status === "reconnect_required"
                ? copy.reconnect
                : t.capabilities.connect;
            return (
              <li
                key={item.server_key}
                className="flex items-center gap-3 py-2"
              >
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium [overflow-wrap:anywhere]">
                    {item.display_name}
                  </p>
                  <p className="text-muted-foreground text-sm">
                    {copy.status[item.status]}
                  </p>
                </div>
                {item.status !== "unavailable" && (
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={change.isPending}
                    aria-label={copy.action(actionLabel, item.display_name)}
                    onClick={() =>
                      change.mutate(
                        {
                          serverKey: item.server_key,
                          action: canDisconnect ? "disconnect" : "connect",
                        },
                        {
                          onSuccess: (authorizationUrl) => {
                            if (authorizationUrl) {
                              window.location.assign(authorizationUrl);
                            }
                          },
                        },
                      )
                    }
                  >
                    {actionLabel}
                  </Button>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
