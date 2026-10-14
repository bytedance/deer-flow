import type { ChannelConnection } from "@/core/channels/types";

/** The Gateway still validates ownership and the binding when the task is saved. */
export function feishuNotificationGroups(
  connections: readonly ChannelConnection[],
): ChannelConnection[] {
  return connections.filter(
    (connection) =>
      connection.provider === "feishu" &&
      connection.status === "connected" &&
      connection.metadata?.chat_type === "group" &&
      typeof connection.workspace_id === "string" &&
      connection.workspace_id.trim().length > 0 &&
      connection.metadata?.chat_id === connection.workspace_id,
  );
}

export function notificationGroupName(
  connection: ChannelConnection | undefined,
): string | null {
  const name = connection?.workspace_name?.trim();
  if (!name) return null;
  return name;
}
