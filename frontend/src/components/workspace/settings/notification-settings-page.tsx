"use client";

import { BellIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { useI18n } from "@/core/i18n/hooks";
import { useNotification } from "@/core/notification/hooks";
import { useLocalSettings } from "@/core/settings";

import { SettingsSection } from "./settings-section";

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

  const handleEnableNotification = async (enabled: boolean) => {
    setSettings("notification", {
      enabled,
    });
  };

  if (!isSupported) {
    return (
      <SettingsSection
        title={t.settings.notification.title}
        description={t.settings.notification.description}
      >
        <p className="text-muted-foreground text-sm">
          {t.settings.notification.notSupported}
        </p>
      </SettingsSection>
    );
  }

  return (
    <SettingsSection
      title={t.settings.notification.title}
      description={
        <div className="flex items-center gap-2">
          <div>{t.settings.notification.description}</div>
          <div>
            <Switch
              disabled={permission !== "granted"}
              checked={
                permission === "granted" && settings.notification.enabled
              }
              onCheckedChange={handleEnableNotification}
            />
          </div>
        </div>
      }
    >
      <div className="flex flex-col gap-4">
        {permission === "default" && (
          <Button onClick={handleRequestPermission} variant="default">
            <BellIcon className="mr-2 size-4" />
            {t.settings.notification.requestPermission}
          </Button>
        )}

        {permission === "denied" && (
          <p className="text-muted-foreground rounded-md border border-amber-200 bg-amber-50 p-3 text-sm dark:border-amber-800 dark:bg-amber-950/50">
            {t.settings.notification.deniedHint}
          </p>
        )}

        {permission === "granted" && settings.notification.enabled && (
          <div className="flex flex-col gap-4">
            <Button onClick={handleTestNotification} variant="outline">
              <BellIcon className="mr-2 size-4" />
              {t.settings.notification.testButton}
            </Button>
          </div>
        )}
      </div>
    </SettingsSection>
  );
}
