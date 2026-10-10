"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  loadAdminUsers,
  updateUserAccount,
  type AdminUser,
} from "@/core/auth/admin-users";
import { useAuth } from "@/core/auth/AuthProvider";
import { useI18n } from "@/core/i18n/hooks";

import { SettingsSection } from "./settings-section";

/**
 * Admin-only user management (RFC #4063 gap 3): list every account and
 * suspend/restore it. Role is displayed read-only — role assignment stays
 * an operator/API concern in this slice.
 */
export function UserSettingsPage() {
  const { user } = useAuth();
  const { t } = useI18n();
  const text = t.settings.users;
  const client = useQueryClient();
  const isAdmin = user?.system_role === "admin";
  const users = useQuery({
    queryKey: ["admin-users", user?.id],
    queryFn: ({ signal }) => loadAdminUsers(signal),
    enabled: isAdmin,
  });
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function toggleDisabled(target: AdminUser) {
    setPending(true);
    setError(null);
    try {
      await updateUserAccount(target.id, { disabled: !target.disabled });
      await client.invalidateQueries({ queryKey: ["admin-users"] });
    } catch (err) {
      // The Gateway's own detail text (the last-active-admin 409 in
      // particular) is the most actionable message available.
      setError(
        err instanceof Error && err.message ? err.message : text.updateFailed,
      );
    } finally {
      setPending(false);
    }
  }

  return (
    <SettingsSection title={text.title} description={text.description}>
      {!isAdmin ? (
        <p>{text.adminOnly}</p>
      ) : (
        <div className="space-y-4">
          <div className="flex gap-2">
            <Button
              variant="outline"
              disabled={users.isFetching}
              onClick={() => void users.refetch()}
            >
              {text.reload}
            </Button>
          </div>
          {users.isLoading && <p role="status">{text.loading}</p>}
          {users.error && (
            <div role="alert">
              <p>{text.failed}</p>
            </div>
          )}
          {error && (
            <p role="alert" className="text-sm text-red-500">
              {error}
            </p>
          )}
          {users.data?.length === 0 && <p>{text.empty}</p>}
          <ul className="space-y-3">
            {users.data?.map((row) => (
              <li
                key={row.id}
                className="flex flex-wrap items-center justify-between gap-3 rounded-lg border p-4"
              >
                <div>
                  <p className="font-medium">{row.email}</p>
                  <p className="text-muted-foreground text-sm">
                    {text.role}: {row.system_role} ·{" "}
                    {row.disabled ? text.disabled : text.active}
                  </p>
                </div>
                <Button
                  variant="outline"
                  disabled={pending}
                  onClick={() => void toggleDisabled(row)}
                >
                  {row.disabled ? text.enable : text.disable}
                </Button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </SettingsSection>
  );
}
