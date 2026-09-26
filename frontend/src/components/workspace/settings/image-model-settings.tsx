"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/core/auth/AuthProvider";
import { useI18n } from "@/core/i18n/hooks";
import {
  imageProfileDraft,
  loadImageProfiles,
  saveImageProfile,
  testImageProfile,
  type ImageProfile,
  type ImageProfileDraft,
  type ImageProvider,
} from "@/core/models/image-management";

import { SettingsSection } from "./settings-section";

const PROVIDERS: ImageProvider[] = ["openai", "gemini", "minimax"];

export function ImageModelSettings() {
  const { user } = useAuth();
  const { t } = useI18n();
  const text = t.settings.imageModels;
  const client = useQueryClient();
  const queryKey = ["image-profiles", user?.id];
  const catalog = useQuery({
    queryKey,
    queryFn: ({ signal }) => loadImageProfiles(signal),
  });
  const [editing, setEditing] = useState<ImageProfile | "new" | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  async function refresh() {
    await client.invalidateQueries({ queryKey });
  }

  async function toggle(profile: ImageProfile) {
    setBusy(profile.name);
    try {
      await saveImageProfile(
        { ...imageProfileDraft(profile), enabled: !profile.enabled },
        profile.revision ?? null,
      );
      await refresh();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : text.failed);
    } finally {
      setBusy(null);
    }
  }

  async function test(profile: ImageProfile, operation: "generation" | "edit") {
    if (!profile.revision) return;
    setBusy(`${profile.name}:${operation}`);
    try {
      const result = await testImageProfile(
        profile.name,
        profile.revision,
        operation,
      );
      toast[result.ok ? "success" : "error"](
        text.results[result.message as keyof typeof text.results] ??
          text.failed,
      );
      await refresh();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : text.failed);
    } finally {
      setBusy(null);
    }
  }

  return (
    <SettingsSection title={text.title} description={text.description}>
      <div className="space-y-4">
        {catalog.data && (
          <p role="status" className="text-sm">
            {text.status}: {text.statuses[catalog.data.status.status]}
          </p>
        )}
        <div className="flex gap-2">
          <Button
            onClick={() => setEditing("new")}
            disabled={!!busy || catalog.isLoading || !!catalog.error}
          >
            {text.add}
          </Button>
          <Button
            variant="outline"
            onClick={() => void catalog.refetch()}
            disabled={catalog.isFetching || !!busy}
          >
            {text.reload}
          </Button>
        </div>
        {catalog.isLoading && <p role="status">{text.loading}</p>}
        {catalog.error && <p role="alert">{text.failed}</p>}
        {catalog.data?.profiles.length === 0 && <p>{text.empty}</p>}
        {catalog.data?.profiles.map((profile) => (
          <div
            key={`${profile.source}:${profile.name}`}
            className="space-y-2 rounded-lg border p-4"
          >
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="font-medium">
                  {profile.display_name || profile.name}
                </p>
                <p className="text-muted-foreground text-sm">
                  {profile.provider} / {profile.model} ·{" "}
                  {profile.source === "config"
                    ? text.serverConfig
                    : profile.enabled
                      ? text.enabled
                      : text.disabled}
                </p>
              </div>
              {profile.source === "managed" && (
                <div className="flex flex-wrap gap-2">
                  <Button
                    variant="outline"
                    disabled={!!busy}
                    onClick={() => setEditing(profile)}
                  >
                    {text.edit}
                  </Button>
                  <Button
                    variant="outline"
                    disabled={!!busy}
                    onClick={() => void toggle(profile)}
                  >
                    {profile.enabled ? text.disable : text.enable}
                  </Button>
                </div>
              )}
            </div>
            <p className="text-muted-foreground text-sm">
              {profile.has_api_key ? text.keySaved : text.keyMissing} ·{" "}
              {profile.verified_generation
                ? text.generationReady
                : text.generationUntested}{" "}
              · {profile.verified_edit ? text.editReady : text.editUntested}
            </p>
            {profile.last_generation_result &&
              profile.last_generation_result !== "success" && (
                <p role="status" className="text-sm">
                  {text.testGeneration}:{" "}
                  {text.results[
                    profile.last_generation_result as keyof typeof text.results
                  ] ?? text.failed}
                </p>
              )}
            {profile.last_edit_result &&
              profile.last_edit_result !== "success" && (
                <p role="status" className="text-sm">
                  {text.testEdit}:{" "}
                  {text.results[
                    profile.last_edit_result as keyof typeof text.results
                  ] ?? text.failed}
                </p>
              )}
            {profile.source === "managed" && (
              <div className="flex flex-wrap gap-2">
                <Button
                  variant="outline"
                  disabled={!!busy || !profile.has_api_key}
                  onClick={() => void test(profile, "generation")}
                >
                  {busy === `${profile.name}:generation`
                    ? text.working
                    : text.testGeneration}
                </Button>
                <Button
                  variant="outline"
                  disabled={!!busy || !profile.has_api_key}
                  onClick={() => void test(profile, "edit")}
                >
                  {busy === `${profile.name}:edit`
                    ? text.working
                    : text.testEdit}
                </Button>
              </div>
            )}
          </div>
        ))}
        {editing && (
          <ImageProfileEditor
            key={editing === "new" ? "new" : editing.name}
            profile={editing === "new" ? undefined : editing}
            activeManaged={
              catalog.data?.profiles.some(
                (item) => item.source === "managed" && item.enabled,
              ) ?? false
            }
            onClose={() => setEditing(null)}
            onSaved={refresh}
          />
        )}
      </div>
    </SettingsSection>
  );
}

function ImageProfileEditor({
  profile,
  activeManaged,
  onClose,
  onSaved,
}: {
  profile?: ImageProfile;
  activeManaged: boolean;
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const { t } = useI18n();
  const text = t.settings.imageModels;
  const [draft, setDraft] = useState<ImageProfileDraft>(() => ({
    ...imageProfileDraft(profile),
    enabled: profile?.enabled ?? !activeManaged,
  }));
  const [key, setKey] = useState("");
  const [clearKey, setClearKey] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  async function save() {
    setPending(true);
    setError("");
    try {
      await saveImageProfile(
        {
          ...draft,
          base_url: draft.base_url?.trim() ? draft.base_url : null,
          size: draft.size?.trim() ? draft.size : null,
          ...(clearKey ? { api_key: "" } : key ? { api_key: key } : {}),
        },
        profile?.revision ?? null,
      );
      await onSaved();
      if (mounted.current) {
        toast.success(text.saved);
        onClose();
      }
    } catch (cause) {
      if (mounted.current)
        setError(cause instanceof Error ? cause.message : text.failed);
    } finally {
      if (mounted.current) setPending(false);
    }
  }

  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open && !pending) onClose();
      }}
    >
      <DialogContent className="flex max-h-[90vh] flex-col overflow-hidden">
        <DialogHeader>
          <DialogTitle>{profile ? text.edit : text.add}</DialogTitle>
          <DialogDescription>{text.formDescription}</DialogDescription>
        </DialogHeader>
        <form
          className="flex min-h-0 flex-col gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            void save();
          }}
        >
          <fieldset
            disabled={pending}
            className="space-y-3 overflow-y-auto pr-1"
          >
            <label className="block space-y-1">
              <span>{text.name}</span>
              <Input
                required
                pattern="[A-Za-z0-9][A-Za-z0-9_.-]{0,99}"
                disabled={!!profile}
                value={draft.name}
                onChange={(event) =>
                  setDraft({ ...draft, name: event.target.value })
                }
              />
            </label>
            <label className="block space-y-1">
              <span>{text.displayName}</span>
              <Input
                maxLength={100}
                value={draft.display_name}
                onChange={(event) =>
                  setDraft({ ...draft, display_name: event.target.value })
                }
              />
            </label>
            <label className="block space-y-1">
              <span>{text.provider}</span>
              <select
                className="border-input bg-background w-full rounded-md border px-3 py-2"
                value={draft.provider}
                onChange={(event) =>
                  setDraft({
                    ...draft,
                    provider: event.target.value as ImageProvider,
                    base_url: "",
                    size: null,
                  })
                }
              >
                {PROVIDERS.map((provider) => (
                  <option key={provider} value={provider}>
                    {text.providers[provider]}
                  </option>
                ))}
              </select>
            </label>
            <label className="block space-y-1">
              <span>{text.modelId}</span>
              <Input
                required
                maxLength={200}
                value={draft.model}
                onChange={(event) =>
                  setDraft({ ...draft, model: event.target.value })
                }
              />
            </label>
            {(draft.provider === "openai" || draft.provider === "minimax") && (
              <label className="block space-y-1">
                <span>{text.endpoint}</span>
                <Input
                  type="url"
                  required={draft.provider === "openai"}
                  placeholder={
                    draft.provider === "openai"
                      ? "https://api.example.com/v1"
                      : "https://api.minimaxi.com"
                  }
                  value={draft.base_url ?? ""}
                  onChange={(event) =>
                    setDraft({ ...draft, base_url: event.target.value })
                  }
                />
              </label>
            )}
            {draft.provider === "openai" && (
              <label className="block space-y-1">
                <span>{text.size}</span>
                <Input
                  placeholder="1536x1024"
                  value={draft.size ?? ""}
                  onChange={(event) =>
                    setDraft({ ...draft, size: event.target.value || null })
                  }
                />
              </label>
            )}
            <label className="block space-y-1">
              <span>API Key</span>
              <Input
                type="password"
                autoComplete="new-password"
                disabled={clearKey}
                value={key}
                placeholder={
                  profile?.has_api_key ? text.keepKey : text.requiredKey
                }
                onChange={(event) => setKey(event.target.value)}
              />
            </label>
            {profile?.has_api_key && (
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={clearKey}
                  onChange={(event) => {
                    setClearKey(event.target.checked);
                    setKey("");
                  }}
                />
                {text.clearKey}
              </label>
            )}
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={draft.enabled}
                onChange={(event) =>
                  setDraft({ ...draft, enabled: event.target.checked })
                }
              />
              {text.enabled}
            </label>
          </fieldset>
          {error && (
            <p role="alert" className="text-sm">
              {error}
            </p>
          )}
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              disabled={pending}
              onClick={onClose}
            >
              {text.cancel}
            </Button>
            <Button type="submit" disabled={pending}>
              {pending ? text.working : text.save}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
