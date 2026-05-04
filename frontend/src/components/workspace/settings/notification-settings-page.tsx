"use client";

import { BellIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { useI18n } from "@/core/i18n/hooks";
import { useNotification } from "@/core/notification/hooks";
import { useLocalSettings } from "@/core/settings";

import { SettingsCard, SettingsRow, SettingsSection } from "./settings-section";

export function NotificationSettingsPage() {
  const { t } = useI18n();
  const { permission, isSupported, requestPermission, showNotification } =
    useNotification();

  const [settings, setSettings] = useLocalSettings();

  const handleRequestPermission = async () => {
    await requestPermission();
  };

  const handleTestNotification = () => {
    showNotification(t.settings.notification.testTitle, {
      body: t.settings.notification.testBody,
    });
  };

  const handleEnableNotification = (enabled: boolean) => {
    setSettings("notification", { enabled });
  };

  if (!isSupported) {
    return (
      <SettingsSection title={t.settings.notification.title}>
        <p className="text-muted-foreground text-sm">
          {t.settings.notification.notSupported}
        </p>
      </SettingsSection>
    );
  }

  return (
    <SettingsSection title={t.settings.notification.title}>
      <SettingsCard>
        <SettingsRow
          label={t.settings.notification.title}
          description={t.settings.notification.description}
          control={
            <Switch
              disabled={permission !== "granted"}
              checked={
                permission === "granted" && settings.notification.enabled
              }
              onCheckedChange={handleEnableNotification}
            />
          }
        />

        {permission === "default" && (
          <SettingsRow
            label={t.settings.notification.requestPermission}
            description={t.settings.notification.description}
            control={
              <Button
                onClick={handleRequestPermission}
                variant="outline"
                size="sm"
              >
                <BellIcon className="mr-2 size-4" />
                {t.settings.notification.requestPermission}
              </Button>
            }
          />
        )}

        {permission === "denied" && (
          <div className="px-5 py-4">
            <p className="text-muted-foreground rounded-md border border-amber-200 bg-amber-50 p-3 text-sm dark:border-amber-800 dark:bg-amber-950/50">
              {t.settings.notification.deniedHint}
            </p>
          </div>
        )}

        {permission === "granted" && settings.notification.enabled && (
          <SettingsRow
            label={t.settings.notification.testButton}
            description={t.settings.notification.testBody}
            control={
              <Button
                onClick={handleTestNotification}
                variant="outline"
                size="sm"
              >
                <BellIcon className="mr-2 size-4" />
                {t.settings.notification.testButton}
              </Button>
            }
          />
        )}
      </SettingsCard>
    </SettingsSection>
  );
}
