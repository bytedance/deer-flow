"use client";

import { useCallback, useEffect, useState } from "react";

import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

type Credential = {
  key_hash: string;
  key_prefix: string;
  revoked_at: string | null;
};
type Profile = {
  id: string;
  name: string;
  disabled: boolean;
  agents: string[];
  models: string[];
  skills: string[];
  tool_groups: string[];
  tools: string[];
  credentials: Credential[];
};

type CapabilityName = "agents" | "models" | "skills" | "tool_groups" | "tools";
type CapabilityDraft = Record<CapabilityName, string>;

const CAPABILITY_FIELDS: Array<{ key: CapabilityName; label: string }> = [
  { key: "agents", label: "Agents" },
  { key: "models", label: "Models" },
  { key: "skills", label: "Skills" },
  { key: "tool_groups", label: "Tool groups" },
  { key: "tools", label: "Tools" },
];

function splitCapabilityList(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function draftFor(profile: Profile): CapabilityDraft {
  return {
    agents: profile.agents.join(", "),
    models: profile.models.join(", "),
    skills: profile.skills.join(", "),
    tool_groups: profile.tool_groups.join(", "),
    tools: profile.tools.join(", "),
  };
}

export default function AppKeysPage() {
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [id, setId] = useState("");
  const [name, setName] = useState("");
  const [agents, setAgents] = useState("");
  const [models, setModels] = useState("");
  const [skills, setSkills] = useState("");
  const [toolGroups, setToolGroups] = useState("");
  const [tools, setTools] = useState("");
  const [editing, setEditing] = useState<{
    id: string;
    capabilities: CapabilityDraft;
  } | null>(null);
  const [secret, setSecret] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const base = getBackendBaseURL();
  const load = useCallback(async () => {
    const res = await fetch(`${base}/api/v1/app-keys/profiles`);
    if (!res.ok)
      throw new Error(
        res.status === 403
          ? "Administrator access is required."
          : "Unable to load App Keys.",
      );
    setProfiles(((await res.json()) as { profiles: Profile[] }).profiles);
  }, [base]);
  useEffect(() => {
    void load().catch((cause: Error) => setError(cause.message));
  }, [load]);
  const create = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    const res = await fetch(`${base}/api/v1/app-keys/profiles`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        id,
        name,
        agents: splitCapabilityList(agents),
        models: splitCapabilityList(models),
        skills: splitCapabilityList(skills),
        tool_groups: splitCapabilityList(toolGroups),
        tools: splitCapabilityList(tools),
      }),
    });
    if (!res.ok) {
      setError("Could not create the profile. Use a unique lowercase ID.");
      return;
    }
    setId("");
    setName("");
    setAgents("");
    setModels("");
    setSkills("");
    setToolGroups("");
    setTools("");
    await load();
  };
  const update = async (profile: Profile, disabled: boolean) => {
    const res = await fetch(
      `${base}/api/v1/app-keys/profiles/${encodeURIComponent(profile.id)}`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ disabled }),
      },
    );
    if (!res.ok) {
      setError("Could not update this profile.");
      return;
    }
    await load();
  };
  const saveCapabilities = async () => {
    if (!editing) return;
    setError(null);
    const res = await fetch(
      `${base}/api/v1/app-keys/profiles/${encodeURIComponent(editing.id)}`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(
          Object.fromEntries(
            CAPABILITY_FIELDS.map(({ key }) => [
              key,
              splitCapabilityList(editing.capabilities[key]),
            ]),
          ),
        ),
      },
    );
    if (!res.ok) {
      setError("Could not save the authorization scope.");
      return;
    }
    setEditing(null);
    await load();
  };
  const createKey = async (profile: Profile) => {
    const res = await fetch(
      `${base}/api/v1/app-keys/profiles/${encodeURIComponent(profile.id)}/credentials`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      },
    );
    if (res.ok) setSecret(((await res.json()) as { app_key: string }).app_key);
  };
  const revoke = async (hash: string) => {
    await fetch(
      `${base}/api/v1/app-keys/credentials/${encodeURIComponent(hash)}`,
      { method: "DELETE" },
    );
    await load();
  };
  return (
    <main className="mx-auto w-full max-w-5xl space-y-8 p-6 md:p-10">
      <section className="border-b pb-6">
        <p className="text-muted-foreground text-sm">Platform administration</p>
        <h1 className="text-3xl font-semibold tracking-tight">App Keys</h1>
        <p className="text-muted-foreground mt-2">
          Create narrowly scoped credentials for external applications. Secrets
          are shown once.
        </p>
      </section>
      {secret && (
        <section className="border border-amber-500/40 bg-amber-500/10 p-4">
          <p className="font-medium">Copy this key now</p>
          <code className="mt-2 block text-sm break-all">{secret}</code>
          <button
            className="mt-3 text-sm underline"
            onClick={() => setSecret(null)}
          >
            I copied it
          </button>
        </section>
      )}
      <form
        onSubmit={create}
        className="grid gap-3 border-b pb-6 md:grid-cols-2"
      >
        <input
          className="bg-background h-9 border px-3"
          value={id}
          onChange={(e) => setId(e.target.value)}
          placeholder="app-id"
          required
        />
        <input
          className="bg-background h-9 border px-3"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Application name"
          required
        />
        {[
          {
            value: agents,
            setValue: setAgents,
            placeholder: "Agents (comma separated)",
          },
          {
            value: models,
            setValue: setModels,
            placeholder: "Models (comma separated)",
          },
          {
            value: skills,
            setValue: setSkills,
            placeholder: "Skills (comma separated)",
          },
          {
            value: toolGroups,
            setValue: setToolGroups,
            placeholder: "Tool groups (comma separated)",
          },
          {
            value: tools,
            setValue: setTools,
            placeholder: "Tools (comma separated)",
          },
        ].map(({ value, setValue, placeholder }) => (
          <input
            key={placeholder}
            className="bg-background h-9 border px-3"
            value={value}
            onChange={(event) => setValue(event.target.value)}
            placeholder={placeholder}
          />
        ))}
        <button className="bg-primary text-primary-foreground h-9 w-fit px-4">
          Create profile
        </button>
      </form>
      {error && <p className="text-destructive text-sm">{error}</p>}
      <section className="divide-y border-t">
        {profiles.map((profile) => (
          <article
            key={profile.id}
            className="grid gap-3 py-5 md:grid-cols-[1fr_auto]"
          >
            <div>
              <div className="flex items-center gap-2">
                <h2 className="font-medium">{profile.name}</h2>
                <span className="text-muted-foreground text-xs">
                  {profile.id}
                </span>
                {profile.disabled && (
                  <span className="text-destructive text-xs">Disabled</span>
                )}
              </div>
              <p className="text-muted-foreground mt-1 text-sm">
                {profile.credentials.length} credential(s) ·{" "}
                {profile.agents.join(", ") || "No agents"} ·{" "}
                {profile.models.join(", ") || "No models"}
              </p>
              {editing?.id === profile.id ? (
                <div className="mt-4 grid gap-2 border-l pl-4 sm:grid-cols-2">
                  {CAPABILITY_FIELDS.map(({ key, label }) => (
                    <label key={key} className="grid gap-1 text-xs">
                      <span className="text-muted-foreground">{label}</span>
                      <input
                        className="bg-background h-8 border px-2 text-sm"
                        value={editing.capabilities[key]}
                        onChange={(event) =>
                          setEditing((current) =>
                            current
                              ? {
                                  ...current,
                                  capabilities: {
                                    ...current.capabilities,
                                    [key]: event.target.value,
                                  },
                                }
                              : null,
                          )
                        }
                        placeholder="Comma separated"
                      />
                    </label>
                  ))}
                  <div className="flex gap-2 pt-2">
                    <button
                      className="bg-primary text-primary-foreground px-3 py-1.5 text-sm"
                      onClick={() => void saveCapabilities()}
                    >
                      Save scope
                    </button>
                    <button
                      className="border px-3 py-1.5 text-sm"
                      onClick={() => setEditing(null)}
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              ) : (
                <p className="text-muted-foreground mt-1 text-xs">
                  Skills: {profile.skills.join(", ") || "None"} · Tool groups:{" "}
                  {profile.tool_groups.join(", ") || "None"} · Tools:{" "}
                  {profile.tools.join(", ") || "None"}
                </p>
              )}
              {profile.credentials.map((credential) => (
                <div
                  key={credential.key_hash}
                  className="text-muted-foreground mt-2 text-xs"
                >
                  {credential.key_prefix}{" "}
                  {credential.revoked_at ? (
                    "(revoked)"
                  ) : (
                    <button
                      className="ml-2 underline"
                      onClick={() => void revoke(credential.key_hash)}
                    >
                      Revoke
                    </button>
                  )}
                </div>
              ))}
            </div>
            <div className="flex items-start gap-2">
              <button
                className="border px-3 py-1.5 text-sm"
                onClick={() => void createKey(profile)}
                disabled={profile.disabled}
              >
                Generate key
              </button>
              <button
                className="border px-3 py-1.5 text-sm"
                onClick={() =>
                  setEditing({
                    id: profile.id,
                    capabilities: draftFor(profile),
                  })
                }
              >
                Edit scope
              </button>
              <button
                className="border px-3 py-1.5 text-sm"
                onClick={() => void update(profile, !profile.disabled)}
              >
                {profile.disabled ? "Enable" : "Disable"}
              </button>
            </div>
          </article>
        ))}
      </section>
    </main>
  );
}
