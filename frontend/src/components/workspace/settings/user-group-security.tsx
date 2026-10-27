"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { useI18n } from "@/core/i18n/hooks";
import {
  securityRequest,
  type ToolResource,
  type UserGroup,
  type UserGroupDetail,
} from "@/core/mcp/user-security";

export function UserGroupSecurityPanel({
  userId,
  resources,
}: {
  userId: string;
  resources: ToolResource[];
}) {
  const { t } = useI18n();
  const text = t.settings.tools.security;
  const client = useQueryClient();
  const [selectedId, setSelectedId] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const groups = useQuery({
    queryKey: ["user-security-groups", userId],
    queryFn: () => securityRequest<{ groups: UserGroup[] }>("/groups"),
  });
  const detail = useQuery({
    queryKey: ["user-security-group", userId, selectedId],
    queryFn: () =>
      securityRequest<UserGroupDetail>(
        `/groups/${encodeURIComponent(selectedId)}`,
      ),
    enabled: Boolean(selectedId),
  });

  async function refresh() {
    await Promise.all([
      client.invalidateQueries({ queryKey: ["user-security-groups", userId] }),
      client.invalidateQueries({ queryKey: ["user-security-group", userId] }),
      client.invalidateQueries({ queryKey: ["user-tool-grants", userId] }),
      client.invalidateQueries({ queryKey: ["user-tool-security", userId] }),
    ]);
  }

  async function create() {
    if (busy || !name.trim()) return;
    setBusy(true);
    setError("");
    try {
      const group = await securityRequest<UserGroup>("/groups", "POST", {
        name: name.trim(),
      });
      setName("");
      setSelectedId(group.id);
      await refresh();
    } catch {
      setError(text.groupSaveError);
    } finally {
      setBusy(false);
    }
  }

  async function change(path: string, method: string, body?: unknown) {
    if (
      busy ||
      detail.isFetching ||
      detail.error ||
      detail.data?.id !== selectedId
    )
      return false;
    const groupId = detail.data.id;
    setBusy(true);
    setError("");
    try {
      await securityRequest(
        `/groups/${encodeURIComponent(groupId)}${path}`,
        method,
        body,
      );
      if (method === "DELETE" && path === "") {
        setSelectedId("");
        client.removeQueries({
          queryKey: ["user-security-group", userId, groupId],
        });
      }
      await refresh();
      return true;
    } catch {
      setError(text.groupSaveError);
      return false;
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="space-y-3">
      <h3 className="font-medium">{text.groupsTitle}</h3>
      <p className="text-muted-foreground text-sm">{text.groupsDescription}</p>
      <form
        className="flex gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          void create();
        }}
      >
        <Input
          aria-label={text.newGroupName}
          placeholder={text.newGroupName}
          value={name}
          maxLength={80}
          required
          disabled={busy}
          onChange={(event) => setName(event.target.value)}
        />
        <Button type="submit" disabled={busy || !name.trim()}>
          {text.createGroup}
        </Button>
      </form>
      {groups.isLoading && <p>{t.common.loading}</p>}
      {groups.error && <p role="alert">{text.groupsLoadError}</p>}
      {groups.data?.groups.length === 0 && (
        <p className="text-muted-foreground text-sm">{text.noGroups}</p>
      )}
      <select
        className="bg-background w-full rounded-md border px-3 py-2 text-sm disabled:opacity-50"
        aria-label={text.selectGroup}
        value={selectedId}
        disabled={busy || groups.isFetching}
        onChange={(event) => {
          setSelectedId(event.target.value);
          setError("");
        }}
      >
        <option value="">{text.selectGroup}</option>
        {groups.data?.groups.map((group) => (
          <option key={group.id} value={group.id}>
            {group.name} ({group.member_count})
          </option>
        ))}
      </select>
      {selectedId && detail.isLoading && <p>{t.common.loading}</p>}
      {selectedId && detail.error && <p role="alert">{text.groupsLoadError}</p>}
      {selectedId && detail.data?.id === selectedId && (
        <GroupEditor
          key={selectedId}
          group={detail.data}
          resources={resources}
          disabled={busy || detail.isFetching || Boolean(detail.error)}
          change={change}
        />
      )}
      {error && <p role="alert">{error}</p>}
    </section>
  );
}

function GroupEditor({
  group,
  resources,
  disabled,
  change,
}: {
  group: UserGroupDetail;
  resources: ToolResource[];
  disabled: boolean;
  change: (path: string, method: string, body?: unknown) => Promise<boolean>;
}) {
  const { t } = useI18n();
  const text = t.settings.tools.security;
  const [name, setName] = useState(group.name);
  const [email, setEmail] = useState("");
  const [confirmDelete, setConfirmDelete] = useState(false);
  return (
    <div className="space-y-4 rounded-md border p-3">
      <form
        className="flex flex-wrap gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          void change("", "PATCH", { name: name.trim() });
        }}
      >
        <Input
          className="min-w-0 flex-1"
          aria-label={text.groupName}
          value={name}
          maxLength={80}
          required
          disabled={disabled}
          onChange={(event) => setName(event.target.value)}
        />
        <Button
          type="submit"
          variant="outline"
          disabled={disabled || !name.trim()}
        >
          {text.renameGroup}
        </Button>
        <Button
          type="button"
          variant="outline"
          disabled={disabled}
          onClick={() => setConfirmDelete(true)}
        >
          {text.deleteGroup}
        </Button>
      </form>
      {confirmDelete && (
        <div
          role="alertdialog"
          aria-label={text.deleteGroup}
          className="space-y-2 rounded-md border p-3"
        >
          <p className="text-sm">{text.deleteGroupDescription}</p>
          <div className="flex gap-2">
            <Button
              variant="destructive"
              disabled={disabled}
              onClick={() => void change("", "DELETE")}
            >
              {text.confirmDeleteGroup}
            </Button>
            <Button
              variant="outline"
              disabled={disabled}
              onClick={() => setConfirmDelete(false)}
            >
              {text.cancelGroupDelete}
            </Button>
          </div>
        </div>
      )}
      <div className="space-y-2">
        <h4 className="text-sm font-medium">{text.membersTitle}</h4>
        <form
          className="flex gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            void change("/members", "POST", { email: email.trim() }).then(
              (saved) => {
                if (saved) setEmail("");
              },
            );
          }}
        >
          <Input
            type="email"
            aria-label={text.memberEmail}
            placeholder={text.memberEmail}
            value={email}
            required
            disabled={disabled}
            onChange={(event) => setEmail(event.target.value)}
          />
          <Button
            type="submit"
            variant="outline"
            disabled={disabled || !email.trim()}
          >
            {text.addMember}
          </Button>
        </form>
        {group.members.length === 0 && (
          <p className="text-muted-foreground text-sm">{text.noMembers}</p>
        )}
        {group.members.map((member) => (
          <div
            key={member.id}
            className="flex items-center justify-between gap-2 text-sm"
          >
            <span className="min-w-0 break-all">
              {member.email ?? member.id}
            </span>
            <Button
              size="sm"
              variant="ghost"
              aria-label={`${text.removeMember} ${member.email ?? member.id}`}
              disabled={disabled}
              onClick={() =>
                void change(
                  `/members/${encodeURIComponent(member.id)}`,
                  "DELETE",
                )
              }
            >
              {text.removeMember}
            </Button>
          </div>
        ))}
      </div>
      <div className="space-y-2">
        <h4 className="text-sm font-medium">{text.groupGrantsTitle}</h4>
        {resources.length === 0 && (
          <p className="text-muted-foreground text-sm">{text.noExtensions}</p>
        )}
        {resources.map((item) => (
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
            <Switch
              aria-label={`${text.groupAccess} ${item.target}`}
              checked={group.grants.some(
                (grant) =>
                  grant.resource === item.resource &&
                  grant.target === item.target,
              )}
              disabled={disabled}
              onCheckedChange={(allowed) =>
                void change("/grants", "PUT", {
                  resource: item.resource,
                  target: item.target,
                  allowed,
                })
              }
            />
          </label>
        ))}
      </div>
    </div>
  );
}
