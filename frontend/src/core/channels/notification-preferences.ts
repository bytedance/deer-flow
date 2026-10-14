import { z } from "zod";

import { throwGatewayApiError } from "@/core/api/errors";
import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

export const notificationProviderIds = [
  "feishu",
  "wecom",
  "wechat",
  "qq",
] as const;
export type NotificationProviderId = (typeof notificationProviderIds)[number];

const preferencesSchema = z.object({
  feishu: z.boolean(),
  wecom: z.boolean(),
  wechat: z.boolean(),
  qq: z.boolean(),
});
export type ChannelNotificationPreferences = z.infer<typeof preferencesSchema>;

async function requestPreferences(
  userId: string,
  signal: AbortSignal,
  patch?: Partial<ChannelNotificationPreferences>,
): Promise<ChannelNotificationPreferences> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/channels/notification-preferences`,
    {
      method: patch ? "PATCH" : "GET",
      headers: {
        "Content-Type": "application/json",
        "X-Expected-User-Id": userId,
      },
      signal,
      ...(patch ? { body: JSON.stringify(patch) } : {}),
    },
  );
  if (!response.ok)
    await throwGatewayApiError(
      response,
      "Unable to load or save notification preferences.",
    );
  return preferencesSchema.parse(await response.json());
}

export function loadChannelNotificationPreferences(
  userId: string,
  signal: AbortSignal,
) {
  return requestPreferences(userId, signal);
}

export function updateChannelNotificationPreference(
  userId: string,
  provider: NotificationProviderId,
  enabled: boolean,
  signal: AbortSignal,
) {
  return requestPreferences(userId, signal, { [provider]: enabled });
}
