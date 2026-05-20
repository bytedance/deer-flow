"use client";

import { AppearanceSettingsPage } from "./appearance-settings-page";
import { NotificationSettingsPage } from "./notification-settings-page";

export function GeneralSettingsPage() {
  return (
    <div className="space-y-10">
      <AppearanceSettingsPage />
      <NotificationSettingsPage />
    </div>
  );
}
