import type { ChannelConnection } from "@/core/channels/types";

function isNonEmptyTrimmedString(value: unknown): value is string {
  return (
    typeof value === "string" &&
    value.trim().length > 0 &&
    value === value.trim()
  );
}

export function isFeishuNotificationGroup(
  connection: ChannelConnection,
): boolean {
  return (
    connection.provider === "feishu" &&
    connection.status === "connected" &&
    connection.metadata?.chat_type === "group" &&
    typeof connection.workspace_id === "string" &&
    connection.workspace_id.trim().length > 0 &&
    connection.metadata?.chat_id === connection.workspace_id
  );
}

export function isQqNotificationGroup(connection: ChannelConnection): boolean {
  if (
    connection.provider !== "qq" ||
    connection.status !== "connected" ||
    connection.metadata?.chat_type !== "group" ||
    typeof connection.workspace_id !== "string"
  ) {
    return false;
  }
  const sepIndex = connection.workspace_id.indexOf(":group:");
  if (sepIndex <= 0) return false;
  const appId = connection.workspace_id.slice(0, sepIndex);
  const groupOpenid = connection.workspace_id.slice(
    sepIndex + ":group:".length,
  );
  if (
    !isNonEmptyTrimmedString(appId) ||
    !isNonEmptyTrimmedString(groupOpenid)
  ) {
    return false;
  }
  const metaOpenid = connection.metadata?.group_openid;
  if (
    metaOpenid !== undefined &&
    metaOpenid !== null &&
    metaOpenid !== groupOpenid
  ) {
    return false;
  }
  return true;
}

export function isWecomNotificationGroup(
  connection: ChannelConnection,
): boolean {
  if (
    connection.provider !== "wecom" ||
    connection.status !== "connected" ||
    connection.metadata?.chattype !== "group" ||
    typeof connection.workspace_id !== "string"
  ) {
    return false;
  }
  const chatid = connection.metadata?.chatid;
  if (!isNonEmptyTrimmedString(chatid)) return false;
  const aibotid = connection.metadata?.aibotid;
  if (aibotid === undefined || aibotid === null || aibotid === "") {
    return connection.workspace_id === `group:${chatid}`;
  }
  if (!isNonEmptyTrimmedString(aibotid)) return false;
  return connection.workspace_id === `${aibotid}:group:${chatid}`;
}

export function isNotificationGroup(connection: ChannelConnection): boolean {
  return (
    isFeishuNotificationGroup(connection) ||
    isQqNotificationGroup(connection) ||
    isWecomNotificationGroup(connection)
  );
}

/** The Gateway still validates ownership and the binding when the task is saved. */
export function notificationGroups(
  connections: readonly ChannelConnection[],
): ChannelConnection[] {
  return connections.filter(isNotificationGroup);
}

export const feishuNotificationGroups = notificationGroups;

function qqGroupId(connection: ChannelConnection): string | null {
  if (!isQqNotificationGroup(connection)) return null;
  const metaOpenid = connection.metadata?.group_openid;
  if (isNonEmptyTrimmedString(metaOpenid)) return metaOpenid;
  if (typeof connection.workspace_id !== "string") return null;
  const sepIndex = connection.workspace_id.indexOf(":group:");
  if (sepIndex <= 0) return null;
  const groupOpenid = connection.workspace_id.slice(
    sepIndex + ":group:".length,
  );
  return isNonEmptyTrimmedString(groupOpenid) ? groupOpenid : null;
}

function wecomGroupId(connection: ChannelConnection): string | null {
  if (!isWecomNotificationGroup(connection)) return null;
  const chatid = connection.metadata?.chatid;
  return isNonEmptyTrimmedString(chatid) ? chatid : null;
}

export function notificationGroupName(
  connection: ChannelConnection | undefined,
): string | null {
  if (!connection) return null;
  const name = connection.workspace_name?.trim();
  if (!name) return null;
  // Older bindings used raw platform IDs as generated labels. Require a real
  // group name or an owner-chosen label before making them selectable.
  if (connection.provider === "qq") {
    const groupId = qqGroupId(connection);
    if (groupId && name === `QQ group (${groupId})`) return null;
  }
  if (connection.provider === "wecom") {
    const groupId = wecomGroupId(connection);
    if (groupId && name === `WeCom group (${groupId})`) return null;
  }
  return name;
}
