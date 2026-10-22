"use client";

import { useContext, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { GatewayApiError } from "@/core/api/errors";
import { AuthQueryScopeContext } from "@/core/auth/query-scope";
import { useI18n } from "@/core/i18n/hooks";
import type { Translations } from "@/core/i18n/locales/types";
import {
  useAgentTracing,
  useSaveAgentTracing,
  useSaveTracingProfile,
  useTracingProfiles,
} from "@/core/tracing/hooks";
import {
  buildProfileRequest,
  profileDraft,
  providerDraft,
  PROVIDER_NAMES,
  type ProfileDraft,
} from "@/core/tracing/profile-draft";
import type {
  AgentTracing,
  TracingMode,
  TracingProfile,
  TracingProfilesResponse,
  TracingProvider,
} from "@/core/tracing/types";

type Text = Translations["tracing"];

function errorMessage(
  error: unknown,
  text: Text,
  conflictMessage = text.conflict,
) {
  if (error instanceof GatewayApiError && error.status === 409)
    return conflictMessage;
  if (error instanceof Error && error.message === "credentials_required")
    return text.credentialsRequired;
  if (error instanceof Error && error.message === "provider_required")
    return text.providerRequired;
  if (error instanceof Error && error.message === "arize_destination_required")
    return text.arizeDestinationRequired;
  return text.saveFailed;
}

/** Keep tracing drafts and cached destinations fenced to the authenticated viewer. */
export function AgentTracingSettings({ agentName }: { agentName: string }) {
  const userId = useContext(AuthQueryScopeContext);
  if (!userId) return null;
  return (
    <TracingSettings
      key={`${userId}:${agentName}`}
      agentName={agentName}
      userId={userId}
    />
  );
}

function TracingSettings({
  agentName,
  userId,
}: {
  agentName: string;
  userId: string;
}) {
  const { t } = useI18n();
  const text = t.tracing;
  const profiles = useTracingProfiles(userId);
  const binding = useAgentTracing(agentName, userId);
  const [generation, setGeneration] = useState(0);
  async function reload() {
    const result = await binding.refetch();
    void profiles.refetch();
    if (result.isSuccess) setGeneration((current) => current + 1);
  }
  return (
    <section
      className="space-y-3 rounded-md border p-3"
      aria-label={text.title}
    >
      <div>
        <p className="text-sm font-medium">{text.title}</p>
        <p className="text-muted-foreground text-xs">{text.description}</p>
      </div>
      {binding.isPending && (
        <p role="status" className="text-muted-foreground text-xs">
          {text.loading}
        </p>
      )}
      {(binding.error ?? profiles.error) && (
        <p role="alert" className="text-destructive text-xs">
          {text.loadFailed}
        </p>
      )}
      {profiles.data && !profiles.data.available && (
        <div role="alert" className="space-y-1 text-xs">
          <p>{text.unavailable}</p>
          {profiles.data.reason && (
            <p className="text-muted-foreground [overflow-wrap:anywhere]">
              {profiles.data.reason}
            </p>
          )}
        </div>
      )}
      {binding.data && (
        <BindingEditor
          key={generation}
          agentName={agentName}
          userId={userId}
          binding={binding.data}
          profiles={profiles.data}
          catalogPending={profiles.isPending}
        />
      )}
      <Button
        type="button"
        size="sm"
        variant="outline"
        disabled={binding.isFetching || profiles.isFetching}
        onClick={() => void reload()}
      >
        {text.reload}
      </Button>
      {profiles.data?.can_manage && profiles.data.available && (
        <ProfileManager userId={userId} profiles={profiles.data.profiles} />
      )}
    </section>
  );
}

function BindingEditor({
  agentName,
  userId,
  binding,
  profiles,
  catalogPending,
}: {
  agentName: string;
  userId: string;
  binding: AgentTracing;
  profiles?: TracingProfilesResponse;
  catalogPending: boolean;
}) {
  const { t } = useI18n();
  const text = t.tracing;
  const save = useSaveAgentTracing(agentName, userId);
  const [mode, setMode] = useState(binding.mode);
  const [profileId, setProfileId] = useState(binding.profile_id ?? "");
  const [revision, setRevision] = useState(binding.revision);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");
  const selectedKnown =
    profiles?.profiles.some((item) => item.id === profileId) ?? false;
  const disabled =
    save.isPending ||
    !binding.can_select ||
    !profiles?.available ||
    (mode === "configured" && !selectedKnown);
  async function apply() {
    if (disabled) return;
    setSaved(false);
    setError("");
    try {
      const result = await save.mutateAsync({
        mode,
        profile_id: mode === "configured" ? profileId : null,
        expected_revision: revision,
      });
      setMode(result.mode);
      setProfileId(result.profile_id ?? "");
      setRevision(result.revision);
      setSaved(true);
    } catch (error) {
      setError(errorMessage(error, text));
    }
  }
  return (
    <div className="space-y-3">
      <div className="space-y-1.5">
        <span className="text-sm">{text.mode}</span>
        <Select
          value={mode}
          onValueChange={(value) => {
            setMode(value as TracingMode);
            setSaved(false);
          }}
          disabled={save.isPending || !binding.can_select}
        >
          <SelectTrigger aria-label={text.mode} className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {(["inherit", "disabled", "configured"] as const).map((value) => (
              <SelectItem value={value} key={value}>
                {text.modes[value]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      {mode === "configured" && (
        <div className="space-y-1.5">
          <span className="text-sm">{text.profile}</span>
          <Select
            value={profileId || "__none__"}
            onValueChange={(value) => {
              setProfileId(value === "__none__" ? "" : value);
              setSaved(false);
            }}
            disabled={
              save.isPending || !binding.can_select || !profiles?.available
            }
          >
            <SelectTrigger aria-label={text.profile} className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="__none__">{text.chooseProfile}</SelectItem>
              {profileId && !selectedKnown && (
                <SelectItem value={profileId} disabled>
                  {text.missingProfile}
                </SelectItem>
              )}
              {profiles?.profiles.map((item) => (
                <SelectItem key={item.id} value={item.id}>
                  {item.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {catalogPending && (
            <p role="status" className="text-muted-foreground text-xs">
              {text.loading}
            </p>
          )}
          {!catalogPending && !selectedKnown && (
            <p className="text-muted-foreground text-xs">
              {text.chooseProfileHint}
            </p>
          )}
        </div>
      )}
      {!binding.can_select && (
        <p className="text-muted-foreground text-xs">
          {binding.error === "tracing_operator_lock"
            ? text.operatorLock
            : text.noPermission}
        </p>
      )}
      <div
        className="bg-muted/40 space-y-1 rounded-md p-2 text-xs"
        aria-label={text.effective}
      >
        <p className="font-medium">
          {profiles?.available === false
            ? text.status.unavailable
            : binding.mode === "disabled"
              ? text.modes.disabled
              : text.status[binding.status]}
        </p>
        <p>
          {text.source}: {binding.source}
        </p>
        <p>
          {text.revision}: {binding.revision} · {text.effectiveRevision}:{" "}
          <span className="[overflow-wrap:anywhere]">
            {binding.effective_revision}
          </span>
        </p>
        {binding.destinations.length === 0 ? (
          <p>{text.noDestinations}</p>
        ) : (
          binding.destinations.map((destination, index) => (
            <div
              key={`${destination.provider}:${index}`}
              className="space-y-0.5 border-t pt-1 [overflow-wrap:anywhere]"
            >
              <p>
                {PROVIDER_NAMES[destination.provider]}
                {destination.project ? ` · ${destination.project}` : ""}
              </p>
              {destination.space_id && (
                <p>
                  {text.spaceId}: {destination.space_id}
                </p>
              )}
              {destination.provider === "langsmith" &&
                destination.workspace_id && (
                  <p>
                    {text.workspaceId}: {destination.workspace_id}
                  </p>
                )}
              {destination.endpoint && (
                <p>
                  {text.endpoint}: {destination.endpoint}
                </p>
              )}
            </div>
          ))
        )}
        <p className="text-muted-foreground">{text.deliveryUnverified}</p>
        {binding.error && (
          <details>
            <summary className="cursor-pointer">{text.errorDetails}</summary>
            <p className="mt-1 [overflow-wrap:anywhere] whitespace-pre-wrap">
              {binding.error}
            </p>
          </details>
        )}
      </div>
      {error && (
        <p role="alert" className="text-destructive text-xs">
          {error}
        </p>
      )}
      {saved && (
        <p role="status" className="text-muted-foreground text-xs">
          {text.saved}
        </p>
      )}
      <Button
        type="button"
        size="sm"
        disabled={disabled}
        onClick={() => void apply()}
      >
        {save.isPending ? text.applying : text.apply}
      </Button>
    </div>
  );
}

function ProfileManager({
  userId,
  profiles,
}: {
  userId: string;
  profiles: TracingProfile[];
}) {
  const { t } = useI18n();
  const text = t.tracing;
  const [editing, setEditing] = useState<TracingProfile | "new" | null>(null);
  return (
    <details className="border-t pt-3">
      <summary className="cursor-pointer text-sm font-medium">
        {text.manageProfiles}
      </summary>
      <div className="mt-3 space-y-3">
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={() => setEditing("new")}
        >
          {text.addProfile}
        </Button>
        {profiles.map((profile) => (
          <div
            key={profile.id}
            className="flex min-w-0 flex-wrap items-center justify-between gap-2 text-sm"
          >
            <span className="min-w-0 [overflow-wrap:anywhere]">
              {profile.name}{" "}
              <span className="text-muted-foreground text-xs">
                ({text.revision} {profile.revision})
              </span>
            </span>
            <Button
              type="button"
              size="sm"
              variant="outline"
              aria-label={`${text.edit} ${profile.name}`}
              onClick={() => setEditing(profile)}
            >
              {text.edit}
            </Button>
          </div>
        ))}
        {editing && (
          <ProfileEditor
            key={
              editing === "new" ? "new" : `${editing.id}:${editing.revision}`
            }
            userId={userId}
            profile={editing === "new" ? undefined : editing}
            onClose={() => setEditing(null)}
          />
        )}
      </div>
    </details>
  );
}

function ProfileEditor({
  userId,
  profile,
  onClose,
}: {
  userId: string;
  profile?: TracingProfile;
  onClose: () => void;
}) {
  const { t } = useI18n();
  const text = t.tracing;
  const [draft, setDraft] = useState<ProfileDraft>(() =>
    profileDraft(profile, userId),
  );
  const [error, setError] = useState("");
  const save = useSaveTracingProfile(userId);
  function update(
    index: number,
    patch: Partial<ProfileDraft["providers"][number]>,
  ) {
    setDraft((current) => ({
      ...current,
      providers: current.providers.map((item, position) =>
        position === index ? { ...item, ...patch } : item,
      ),
    }));
  }
  async function submit() {
    setError("");
    try {
      await save.mutateAsync({
        id: profile?.id ?? null,
        body: buildProfileRequest(draft, profile),
      });
      onClose();
    } catch (error) {
      setError(errorMessage(error, text, text.profileConflict));
    }
  }
  return (
    <div className="space-y-3 rounded-md border p-3">
      <fieldset disabled={save.isPending} className="space-y-3">
        <label className="block space-y-1 text-sm">
          <span>{text.profileName}</span>
          <Input
            value={draft.name}
            onChange={(event) =>
              setDraft({ ...draft, name: event.target.value })
            }
          />
        </label>
        <label className="block space-y-1 text-sm">
          <span>{text.allowedUsers}</span>
          <Input
            value={draft.allowed_user_ids}
            onChange={(event) =>
              setDraft({ ...draft, allowed_user_ids: event.target.value })
            }
          />
        </label>
        <p className="text-muted-foreground text-xs">{text.allowedUsersHint}</p>
        <div
          className="flex flex-wrap gap-3"
          role="group"
          aria-label={text.providers}
        >
          {(Object.keys(PROVIDER_NAMES) as TracingProvider[]).map(
            (provider) => (
              <label
                className="flex items-center gap-1.5 text-sm"
                key={provider}
              >
                <input
                  type="checkbox"
                  checked={draft.providers.some(
                    (item) => item.provider === provider,
                  )}
                  onChange={(event) =>
                    setDraft((current) => ({
                      ...current,
                      providers: event.target.checked
                        ? [...current.providers, providerDraft(provider)]
                        : current.providers.filter(
                            (item) => item.provider !== provider,
                          ),
                    }))
                  }
                />
                {PROVIDER_NAMES[provider]}
              </label>
            ),
          )}
        </div>
        {draft.providers.map((provider, index) => {
          const name = PROVIDER_NAMES[provider.provider];
          const previous = profile?.providers.find(
            (item) => item.provider === provider.provider,
          );
          return (
            <div
              key={provider.provider}
              className="space-y-2 rounded-md border p-2"
            >
              <p className="text-sm font-medium">{name}</p>
              <label className="block space-y-1 text-sm">
                <span>{text.endpoint}</span>
                <Input
                  type="url"
                  aria-label={`${name} ${text.endpoint}`}
                  value={provider.endpoint}
                  onChange={(event) =>
                    update(index, { endpoint: event.target.value })
                  }
                />
              </label>
              <label className="block space-y-1 text-sm">
                <span>{text.project}</span>
                <Input
                  aria-label={`${name} ${text.project}`}
                  value={provider.project}
                  onChange={(event) =>
                    update(index, { project: event.target.value })
                  }
                />
              </label>
              {provider.provider === "arize" && (
                <>
                  <label className="block space-y-1 text-sm">
                    <span>{text.spaceId}</span>
                    <Input
                      aria-label={`${name} ${text.spaceId}`}
                      value={provider.space_id}
                      onChange={(event) =>
                        update(index, { space_id: event.target.value })
                      }
                    />
                  </label>
                  <label className="block space-y-1 text-sm">
                    <span>{text.transport}</span>
                    <select
                      className="border-input bg-background h-9 w-full rounded-md border px-2"
                      aria-label={`${name} ${text.transport}`}
                      value={provider.transport}
                      onChange={(event) =>
                        update(index, {
                          transport: event.target.value as "http" | "grpc",
                        })
                      }
                    >
                      <option value="http">HTTP</option>
                      <option value="grpc">gRPC</option>
                    </select>
                  </label>
                </>
              )}
              {provider.provider === "langsmith" && (
                <label className="block space-y-1 text-sm">
                  <span>{text.workspaceIdOptional}</span>
                  <Input
                    aria-label={`${name} ${text.workspaceIdOptional}`}
                    value={provider.workspace_id}
                    onChange={(event) =>
                      update(index, { workspace_id: event.target.value })
                    }
                  />
                </label>
              )}
              {provider.provider === "langfuse" && (
                <label className="block space-y-1 text-sm">
                  <span>{text.publicKey}</span>
                  <Input
                    aria-label={`${name} ${text.publicKey}`}
                    value={provider.public_key}
                    onChange={(event) =>
                      update(index, { public_key: event.target.value })
                    }
                  />
                </label>
              )}
              <label className="block space-y-1 text-sm">
                <span>
                  {provider.provider === "langfuse"
                    ? text.secretKey
                    : text.apiKey}
                </span>
                <Input
                  type="password"
                  autoComplete="new-password"
                  aria-label={`${name} ${provider.provider === "langfuse" ? text.secretKey : text.apiKey}`}
                  value={
                    provider.provider === "langfuse"
                      ? provider.secret_key
                      : provider.api_key
                  }
                  placeholder={
                    (
                      provider.provider === "langfuse"
                        ? previous?.has_secret_key
                        : previous?.has_api_key
                    )
                      ? text.credentialStored
                      : ""
                  }
                  onChange={(event) =>
                    update(
                      index,
                      provider.provider === "langfuse"
                        ? { secret_key: event.target.value }
                        : { api_key: event.target.value },
                    )
                  }
                />
              </label>
              <p className="text-muted-foreground text-xs">
                {text.rotationHint}
              </p>
            </div>
          );
        })}
      </fieldset>
      {error && (
        <p role="alert" className="text-destructive text-xs">
          {error}
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        <Button
          type="button"
          size="sm"
          disabled={save.isPending || !draft.name.trim()}
          onClick={() => void submit()}
        >
          {save.isPending ? text.applying : text.saveProfile}
        </Button>
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={save.isPending}
          onClick={onClose}
        >
          {t.common.cancel}
        </Button>
      </div>
    </div>
  );
}
