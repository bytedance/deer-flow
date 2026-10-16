"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { GatewayApiError } from "@/core/api/errors";
import { useAuth } from "@/core/auth/AuthProvider";
import { listChannelProviders } from "@/core/channels/api";
import {
  loadChannelNotificationPreferences,
  notificationEventIds,
  notificationProviderIds,
  updateChannelNotificationPreference,
  type NotificationPreferenceKey,
} from "@/core/channels/notification-preferences";
import { useI18n } from "@/core/i18n/hooks";
import { isStaticWebsiteOnly } from "@/core/static-mode";

import { SettingsSection } from "./settings-section";

export function ChannelNotificationSettings() {
  const { user } = useAuth();
  const { t } = useI18n();
  const text = t.settings.notification.channels;
  return (
    <SettingsSection title={text.title} description={text.description}>
      {user && !isStaticWebsiteOnly() ? (
        <UserChannelNotifications key={user.id} userId={user.id} />
      ) : (
        <p className="text-muted-foreground text-sm">{text.unavailable}</p>
      )}
    </SettingsSection>
  );
}

function UserChannelNotifications({ userId }: { userId: string }) {
  const { t } = useI18n();
  const text = t.settings.notification.channels;
  const client = useQueryClient();
  const queryKey = ["channelNotificationSettings", userId];
  const query = useQuery({
    queryKey,
    queryFn: async ({ signal }) => {
      const [preferences, catalog] = await Promise.all([
        loadChannelNotificationPreferences(userId, signal),
        listChannelProviders({ signal }),
      ]);
      return { preferences, catalog };
    },
    retry: false,
    gcTime: 0,
  });
  const [saving, setSaving] = useState<NotificationPreferenceKey | null>(null);
  const [saveFailed, setSaveFailed] = useState(false);
  const saveRequest = useRef<AbortController | null>(null);
  useEffect(() => () => saveRequest.current?.abort(), []);

  async function save(key: NotificationPreferenceKey, enabled: boolean) {
    if (
      saveRequest.current ||
      !query.data ||
      Boolean(query.data.preferences[key]) === enabled
    )
      return;
    const request = new AbortController();
    saveRequest.current = request;
    setSaving(key);
    setSaveFailed(false);
    try {
      const preferences = await updateChannelNotificationPreference(
        userId,
        key,
        enabled,
        request.signal,
      );
      if (request.signal.aborted) return;
      // An older focus/refetch result must not overwrite the confirmed PATCH.
      await client.cancelQueries({ queryKey });
      if (request.signal.aborted) return;
      client.setQueryData<typeof query.data>(queryKey, (previous) =>
        previous ? { ...previous, preferences } : previous,
      );
    } catch {
      if (!request.signal.aborted) setSaveFailed(true);
    } finally {
      if (!request.signal.aborted) {
        setSaving(null);
        saveRequest.current = null;
      }
    }
  }

  if (query.isPending)
    return (
      <p role="status" className="text-muted-foreground text-sm">
        {text.loading}
      </p>
    );
  if (query.error) {
    const unsupported =
      query.error instanceof GatewayApiError &&
      [404, 405].includes(query.error.status);
    return (
      <div className="space-y-2">
        <p role="alert" className="text-muted-foreground text-sm">
          {unsupported ? text.unavailable : text.loadFailed}
        </p>
        {!unsupported && (
          <Button
            variant="outline"
            size="sm"
            onClick={() => void query.refetch()}
            disabled={query.isFetching}
          >
            {text.retry}
          </Button>
        )}
      </div>
    );
  }
  const { preferences, catalog } = query.data;
  const providers = notificationProviderIds.filter(
    (id) =>
      catalog.enabled &&
      catalog.providers.some(
        (provider) =>
          provider.provider === id &&
          provider.proactive_notifications === true &&
          provider.connection_status === "connected",
      ),
  );
  return (
    <div className="space-y-3">
      {providers.length === 0 && (
        <p className="text-muted-foreground text-sm">{text.empty}</p>
      )}
      {providers.map((provider) => (
        <div key={provider} className="flex items-center justify-between gap-4">
          <label htmlFor={`notify-${provider}`} className="text-sm">
            {text.providers[provider]}
          </label>
          <Switch
            id={`notify-${provider}`}
            aria-label={text.toggleLabel(text.providers[provider])}
            checked={preferences[provider]}
            disabled={saving !== null || query.isFetching}
            onCheckedChange={(enabled) => void save(provider, enabled)}
          />
        </div>
      ))}
      {providers.length > 0 && (
        <div className="border-border/60 space-y-3 border-t pt-3">
          <div className="space-y-1">
            <p className="text-sm font-medium">{text.eventsTitle}</p>
            <p className="text-muted-foreground text-xs">
              {text.eventsDescription}
            </p>
          </div>
          {notificationEventIds.map((event) => (
            <div
              key={event}
              className="flex items-center justify-between gap-4"
            >
              <label htmlFor={`notify-event-${event}`} className="text-sm">
                {text.events[event]}
              </label>
              <Switch
                id={`notify-event-${event}`}
                aria-label={text.eventToggleLabel(text.events[event])}
                checked={Boolean(preferences[event])}
                disabled={saving !== null || query.isFetching}
                onCheckedChange={(enabled) => void save(event, enabled)}
              />
            </div>
          ))}
        </div>
      )}
      {saving && (
        <p role="status" className="text-muted-foreground text-sm">
          {text.saving}
        </p>
      )}
      {saveFailed && (
        <p role="alert" className="text-destructive text-sm">
          {text.saveFailed}
        </p>
      )}
    </div>
  );
}
