"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { accountProfile } from "@/core/auth/profile";
import { useI18n } from "@/core/i18n/hooks";

export function AccountNicknameSettings({ userId }: { userId: string }) {
  const { t } = useI18n();
  const copy = t.settings.account;
  const client = useQueryClient();
  const queryKey = ["account-profile", userId];
  const query = useQuery({
    queryKey,
    queryFn: () => accountProfile(),
    retry: false,
  });
  const [draft, setDraft] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");
  const value = draft ?? query.data?.nickname ?? "";

  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (saving || !query.data) return;
    setSaving(true);
    setError("");
    setSaved(false);
    try {
      await client.cancelQueries({ queryKey });
      const profile = await accountProfile(value.trim());
      client.setQueryData(queryKey, profile);
      setDraft(null);
      setSaved(true);
    } catch {
      setError(copy.nicknameSaveFailed);
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={save} className="mt-5 max-w-sm space-y-3">
      <label htmlFor="account-nickname" className="text-sm font-medium">
        {copy.nickname}
      </label>
      <Input
        id="account-nickname"
        autoComplete="nickname"
        value={value}
        maxLength={80}
        placeholder={copy.nicknamePlaceholder}
        aria-describedby="account-nickname-hint"
        disabled={saving || !query.data}
        onChange={(event) => {
          setDraft(event.target.value);
          setSaved(false);
          setError("");
        }}
      />
      <p id="account-nickname-hint" className="text-muted-foreground text-sm">
        {copy.nicknameHint}
      </p>
      {query.error ? (
        <div className="space-y-2">
          <p role="alert" className="text-destructive text-sm">
            {copy.nicknameLoadFailed}
          </p>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={query.isFetching}
            onClick={() => void query.refetch()}
          >
            {copy.retry}
          </Button>
        </div>
      ) : (
        <Button
          type="submit"
          variant="outline"
          size="sm"
          disabled={
            saving ||
            !query.data ||
            value.trim() === (query.data.nickname ?? "")
          }
        >
          {saving ? copy.updating : copy.saveNickname}
        </Button>
      )}
      {error && (
        <p role="alert" className="text-destructive text-sm">
          {error}
        </p>
      )}
      {saved && (
        <p role="status" className="text-sm">
          {copy.nicknameSaved}
        </p>
      )}
    </form>
  );
}
