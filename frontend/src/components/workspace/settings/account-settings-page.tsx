"use client";

import { LogOutIcon } from "@/components/ui/icons";

import { Button } from "@/components/ui/button";
import { useAuth } from "@/core/auth/AuthProvider";
import { useI18n } from "@/core/i18n/hooks";

import { SettingsSection } from "./settings-section";

export function AccountSettingsPage() {
  const { user, logout } = useAuth();
  const { t } = useI18n();

  return (
    <div className="space-y-8">
      <SettingsSection title={t.settings.account.profileTitle}>
        <div className="space-y-2">
          <div className="grid grid-cols-[max-content_max-content] items-center gap-4">
            <span className="text-muted-foreground text-sm">
              {t.settings.account.realName}
            </span>
            <span className="text-sm font-medium">{user?.real_name || "—"}</span>
            <span className="text-muted-foreground text-sm">
              {t.settings.account.userName}
            </span>
            <span className="text-sm font-medium">{user?.user_name || "—"}</span>
            <span className="text-muted-foreground text-sm">
              {t.settings.account.role}
            </span>
            <span className="text-sm font-medium capitalize">
              {user?.system_role ?? "—"}
            </span>
          </div>
        </div>
      </SettingsSection>

      <SettingsSection title="" description="">
        <Button
          variant="destructive"
          size="sm"
          onClick={() => void logout()}
          className="gap-2"
        >
          <LogOutIcon className="size-4" />
          {t.settings.account.signOut}
        </Button>
      </SettingsSection>
    </div>
  );
}
