"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/core/auth/AuthProvider";
import { useI18n } from "@/core/i18n/hooks";
import {
  securityRequest,
  type PersonalOverride,
  type ToolResource,
  type UserToolGrants,
  type UserToolSecurity,
} from "@/core/mcp/user-security";

import { UserGroupSecurityPanel } from "./user-group-security";

export function UserToolSecurityPanel() {
  const { user } = useAuth();
  return user ? <UserSecurityContent key={user.id} userId={user.id} /> : null;
}

function UserSecurityContent({ userId }: { userId: string }) {
  const client = useQueryClient();
  const { t } = useI18n();
  const text = t.settings.tools.security;
  const query = useQuery({
    queryKey: ["user-tool-security", userId],
    queryFn: () => securityRequest<UserToolSecurity>("/me"),
  });
  const [email, setEmail] = useState("");
  const [selectedEmail, setSelectedEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const grants = useQuery({
    queryKey: ["user-tool-grants", userId, selectedEmail],
    queryFn: () =>
      securityRequest<UserToolGrants>(
        `/grants?email=${encodeURIComponent(selectedEmail)}`,
      ),
    enabled: Boolean(selectedEmail && query.data?.admin),
  });
  if (query.isLoading) return <p>{t.common.loading}</p>;
  if (query.error) return <p role="alert">{text.loadError}</p>;
  const data = query.data;
  if (!data?.enabled) return null;

  async function changeGrant(item: ToolResource, mode: PersonalOverride) {
    if (!grants.data || busy || grants.isFetching) return;
    setBusy(true);
    setError("");
    try {
      await securityRequest("/overrides", "PUT", {
        email: grants.data.email,
        resource: item.resource,
        target: item.target,
        mode,
      });
      await grants.refetch();
      await client.invalidateQueries({
        queryKey: ["user-tool-security", userId],
      });
    } catch {
      setError(text.saveError);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mt-6 space-y-6 border-t pt-6">
      {data.resources.length === 0 && (
        <p className="text-muted-foreground text-sm">{text.noExtensions}</p>
      )}
      <section className="space-y-3">
        <h3 className="font-medium">{text.personalTitle}</h3>
        <p className="text-muted-foreground text-sm">
          {text.personalDescription}
        </p>
        {data.resources.filter(
          (item) => item.resource === "mcp_server" && item.allowed,
        ).length === 0 && (
          <p className="text-muted-foreground text-sm">{text.noServers}</p>
        )}
        {data.resources
          .filter((item) => item.resource === "mcp_server" && item.allowed)
          .map((item) => (
            <PersonalCredential
              key={item.target}
              item={item}
              configured={data.credentials.includes(item.target)}
              refresh={() => query.refetch()}
            />
          ))}
        {data.credentials
          .filter(
            (server) =>
              !data.resources.some(
                (item) =>
                  item.resource === "mcp_server" &&
                  item.target === server &&
                  item.allowed,
              ),
          )
          .map((server) => (
            <PersonalCredential
              key={server}
              item={{ resource: "mcp_server", target: server, allowed: false }}
              configured
              refresh={() => query.refetch()}
            />
          ))}
      </section>
      {!data.admin && (
        <section className="space-y-2">
          <h3 className="font-medium">{text.myTools}</h3>
          <p className="text-muted-foreground text-sm">{text.requestAccess}</p>
          {data.resources
            .filter((item) => item.allowed)
            .map((item) => (
              <div key={`${item.resource}:${item.target}`} className="text-sm">
                {item.label ?? item.target}
                <span className="text-muted-foreground ml-2 text-xs">
                  {text.resourceTypes[item.resource]}
                  {item.server ? ` · ${item.server}` : ""}
                </span>
              </div>
            ))}
        </section>
      )}
      {data.admin && (
        <UserGroupSecurityPanel userId={userId} resources={data.resources} />
      )}
      {data.admin && (
        <section className="space-y-3">
          <h3 className="font-medium">{text.grantsTitle}</h3>
          <p className="text-muted-foreground text-sm">
            {text.grantsDescription}
          </p>
          <p className="text-muted-foreground text-sm">
            {text.overrideDescription}
          </p>
          <form
            className="flex gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              setSelectedEmail(email.trim());
            }}
          >
            <Input
              type="email"
              aria-label={text.userEmail}
              placeholder={text.userEmail}
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              required
              disabled={busy}
            />
            <Button type="submit" disabled={busy}>
              {text.loadUser}
            </Button>
          </form>
          {grants.isFetching && <p>{t.common.loading}</p>}
          {grants.error && <p role="alert">{text.userError}</p>}
          {grants.data && (
            <div className="space-y-2">
              <p className="text-sm font-medium">{grants.data.email}</p>
              <div className="text-muted-foreground text-sm">
                <span>{text.memberships}: </span>
                {grants.data.groups.length
                  ? grants.data.groups.map((group) => (
                      <span
                        key={group.id}
                        className="mr-2 inline-block rounded border px-2 py-1"
                      >
                        {group.name}
                      </span>
                    ))
                  : text.noMemberships}
              </div>
              {grants.data.admin ? (
                <p className="text-muted-foreground text-sm">
                  {text.adminAccess}
                </p>
              ) : (
                (grants.data.resources ?? data.resources).map((item) => (
                  <label
                    key={`${item.resource}:${item.target}`}
                    className="flex items-center justify-between gap-3 rounded-md border p-3"
                  >
                    <span className="min-w-0 text-sm break-all">
                      {item.label ?? item.target}
                      <span className="text-muted-foreground ml-2 text-xs">
                        {text.resourceTypes[item.resource]}
                        {item.server ? ` · ${item.server}` : ""}
                      </span>
                    </span>
                    <span className="flex shrink-0 flex-col items-end gap-1">
                      <span
                        className="text-xs"
                        aria-label={`${text.effectiveAccess} ${item.target}`}
                      >
                        {grants.data.grants.some(
                          (grant) =>
                            grant.resource === item.resource &&
                            grant.target === item.target,
                        )
                          ? text.allowed
                          : text.denied}
                      </span>
                      <select
                        className="bg-background rounded-md border px-2 py-1 text-sm disabled:opacity-50"
                        aria-label={`${text.personalOverride} ${item.target}`}
                        value={
                          grants.data.denied.some(
                            (grant) =>
                              grant.resource === item.resource &&
                              grant.target === item.target,
                          )
                            ? "deny"
                            : grants.data.direct_grants.some(
                                  (grant) =>
                                    grant.resource === item.resource &&
                                    grant.target === item.target,
                                )
                              ? "allow"
                              : "inherit"
                        }
                        disabled={
                          busy || grants.isFetching || Boolean(grants.error)
                        }
                        onChange={(event) =>
                          void changeGrant(
                            item,
                            event.target.value as PersonalOverride,
                          )
                        }
                      >
                        <option value="inherit">{text.inherit}</option>
                        <option value="allow">{text.allow}</option>
                        <option value="deny">{text.deny}</option>
                      </select>
                    </span>
                  </label>
                ))
              )}
            </div>
          )}
          {error && <p role="alert">{error}</p>}
        </section>
      )}
    </div>
  );
}

function PersonalCredential({
  item,
  configured,
  refresh,
}: {
  item: ToolResource;
  configured: boolean;
  refresh: () => Promise<unknown>;
}) {
  const { t } = useI18n();
  const text = t.settings.tools.security;
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function save(remove = false) {
    setBusy(true);
    setError("");
    try {
      await securityRequest(
        `/credentials/${encodeURIComponent(item.target)}`,
        remove ? "DELETE" : "PUT",
        remove ? undefined : { credential: value },
      );
      setValue("");
      await refresh();
    } catch {
      setError(text.saveError);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="space-y-2 rounded-md border p-3">
      <div className="flex justify-between gap-2 text-sm">
        <span className="font-medium break-all">{item.target}</span>
        <span>{configured ? text.configured : text.notConfigured}</span>
      </div>
      {item.credential_supported && item.allowed ? (
        <form
          className="flex flex-wrap gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            void save();
          }}
        >
          <Input
            className="min-w-0 flex-1"
            type="password"
            autoComplete="new-password"
            aria-label={`${text.credential} ${item.target}`}
            placeholder="Bearer … / API Key"
            value={value}
            onChange={(event) => setValue(event.target.value)}
            disabled={busy}
          />
          <Button type="submit" disabled={busy || !value}>
            {text.save}
          </Button>
        </form>
      ) : (
        <p className="text-muted-foreground text-sm">{text.unsupported}</p>
      )}
      {configured && (
        <Button
          size="sm"
          variant="outline"
          disabled={busy}
          onClick={() => void save(true)}
        >
          {text.remove}
        </Button>
      )}
      {error && <p role="alert">{error}</p>}
    </div>
  );
}
