"use client";

import { LogOutIcon } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { fetch, getCsrfHeaders } from "@/core/api/fetcher";
import { useAuth } from "@/core/auth/AuthProvider";
import { parseAuthError } from "@/core/auth/types";

import { SettingsCard, SettingsRow, SettingsSection } from "./settings-section";

export function AccountSettingsPage() {
  const { user, logout } = useAuth();
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleChangePassword = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setMessage("");

    if (newPassword !== confirmPassword) {
      setError("New passwords do not match");
      return;
    }
    if (newPassword.length < 8) {
      setError("Password must be at least 8 characters");
      return;
    }

    setLoading(true);
    try {
      const res = await fetch("/api/v1/auth/change-password", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...getCsrfHeaders(),
        },
        body: JSON.stringify({
          current_password: currentPassword,
          new_password: newPassword,
        }),
      });

      if (!res.ok) {
        const data = await res.json();
        const authError = parseAuthError(data);
        setError(authError.message);
        return;
      }

      setMessage("Password changed successfully");
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
    } catch {
      setError("Network error. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  const initial = (
    user?.email?.[0] ??
    user?.system_role?.[0] ??
    "?"
  ).toUpperCase();

  return (
    <div className="space-y-10">
      <SettingsSection title="Profile">
        <SettingsCard>
          <div className="flex items-center gap-4 px-5 py-4">
            <div className="bg-primary text-primary-foreground flex size-12 shrink-0 items-center justify-center rounded-full text-base font-semibold">
              {initial}
            </div>
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm font-semibold">
                {user?.email ?? "—"}
              </div>
              <div className="text-muted-foreground mt-0.5 text-xs capitalize">
                {user?.system_role ?? "—"}
              </div>
            </div>
          </div>
        </SettingsCard>
      </SettingsSection>

      <SettingsSection
        title="Change Password"
        description="Update your account password. Use at least 8 characters."
      >
        <SettingsCard>
          <form onSubmit={handleChangePassword}>
            <SettingsRow
              size="compact"
              label="Current password"
              control={
                <Input
                  type="password"
                  placeholder="••••••••"
                  value={currentPassword}
                  onChange={(e) => setCurrentPassword(e.target.value)}
                  required
                  className="w-[260px]"
                />
              }
            />
            <SettingsRow
              size="compact"
              label="New password"
              control={
                <Input
                  type="password"
                  placeholder="At least 8 characters"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  required
                  minLength={8}
                  className="w-[260px]"
                />
              }
            />
            <SettingsRow
              size="compact"
              label="Confirm new password"
              control={
                <Input
                  type="password"
                  placeholder="Re-enter new password"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  required
                  minLength={8}
                  className="w-[260px]"
                />
              }
            />
            {(error || message) && (
              <div className="px-5 py-2">
                {error && <p className="text-sm text-red-500">{error}</p>}
                {message && (
                  <p className="text-sm text-emerald-600 dark:text-emerald-400">
                    {message}
                  </p>
                )}
              </div>
            )}
            <div className="flex justify-end px-5 py-3">
              <Button
                type="submit"
                variant="default"
                size="sm"
                disabled={loading}
              >
                {loading ? "Updating..." : "Update password"}
              </Button>
            </div>
          </form>
        </SettingsCard>
      </SettingsSection>

      <SettingsSection title="Session">
        <SettingsCard>
          <SettingsRow
            label="Sign out"
            description="Sign out of this device. You can sign back in any time."
            control={
              <Button
                variant="destructive"
                size="sm"
                onClick={logout}
                className="gap-2"
              >
                <LogOutIcon className="size-4" />
                Sign Out
              </Button>
            }
          />
        </SettingsCard>
      </SettingsSection>
    </div>
  );
}
