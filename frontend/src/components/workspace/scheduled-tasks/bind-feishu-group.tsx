"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { connectChannelProvider } from "@/core/channels/api";
import { channelConnectionsQueryKey } from "@/core/channels/hooks";
import type { ChannelConnectResponse } from "@/core/channels/types";
import { useI18n } from "@/core/i18n/hooks";

import { fill } from "./shared";

type GroupChannelProvider = "feishu" | "wecom" | "qq";

interface CachedGroupBinding {
  data: ChannelConnectResponse;
  expiresAt: number;
  groupName?: string;
}

/** Group binding needs its own command; a connected private chat is not completion. */
export function BindFeishuGroup() {
  const { t, locale } = useI18n();
  const labels = t.scheduledTasks.notificationGroup;
  const queryClient = useQueryClient();
  const [visible, setVisible] = useState(false);
  const [provider, setProvider] = useState<GroupChannelProvider>("feishu");
  const [namesByProvider, setNamesByProvider] = useState<
    Partial<Record<GroupChannelProvider, string>>
  >({});
  const groupNameId = useId();
  const [cachedByProvider, setCachedByProvider] = useState<
    Partial<Record<GroupChannelProvider, CachedGroupBinding>>
  >({});
  const [copied, setCopied] = useState(false);
  const [copyFailed, setCopyFailed] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const binding = useMutation({
    mutationFn: ({
      targetProvider,
      groupName,
    }: {
      targetProvider: GroupChannelProvider;
      groupName?: string;
    }) =>
      groupName
        ? connectChannelProvider(targetProvider, { groupName })
        : connectChannelProvider(targetProvider),
    onSuccess: (result, { targetProvider, groupName }) => {
      setCopied(false);
      setCopyFailed(false);
      setCachedByProvider((prev) => ({
        ...prev,
        [targetProvider]: {
          data: result,
          expiresAt: Date.now() + result.expires_in * 1000,
          groupName,
        },
      }));
    },
  });
  const currentCached = cachedByProvider[provider];
  const needsName = provider !== "feishu";
  const groupName = (namesByProvider[provider] ?? "").trim();
  const command =
    currentCached && (!needsName || currentCached.groupName === groupName)
      ? `/connect ${currentCached.data.code}`
      : "";
  const expiresAt = currentCached?.expiresAt ?? null;
  const startBind = (targetProvider: GroupChannelProvider) => {
    setProvider(targetProvider);
    setVisible(true);
    setCopied(false);
    setCopyFailed(false);
    const cached = cachedByProvider[targetProvider];
    const name = namesByProvider[targetProvider]?.trim();
    if (
      (!cached ||
        cached.expiresAt <= Date.now() ||
        cached.groupName !== name) &&
      (targetProvider === "feishu" || name)
    ) {
      binding.mutate({ targetProvider, groupName: name });
    }
  };
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(command);
      setCopied(true);
      setCopyFailed(false);
    } catch {
      setCopyFailed(true);
    }
  };
  const refresh = async () => {
    setRefreshing(true);
    try {
      await queryClient.invalidateQueries({
        queryKey: channelConnectionsQueryKey,
      });
    } finally {
      setRefreshing(false);
    }
  };

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap gap-2">
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={binding.isPending}
          onClick={() => startBind("feishu")}
        >
          {labels.bind}
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={binding.isPending}
          onClick={() => startBind("wecom")}
        >
          {labels.bindWecom}
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={binding.isPending}
          onClick={() => startBind("qq")}
        >
          {labels.bindQq}
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          disabled={refreshing}
          onClick={() => void refresh()}
        >
          {labels.refresh}
        </Button>
      </div>
      {visible && (
        <div
          className="bg-muted/30 flex flex-col gap-2 rounded-md border p-3"
          data-testid="feishu-group-binding"
        >
          <p className="text-sm">{labels.bindInstructions}</p>
          {needsName && (
            <>
              <label htmlFor={groupNameId} className="text-sm font-medium">
                {labels.name}
              </label>
              <Input
                id={groupNameId}
                value={namesByProvider[provider] ?? ""}
                maxLength={256}
                onChange={(event) => {
                  setNamesByProvider((previous) => ({
                    ...previous,
                    [provider]: event.target.value,
                  }));
                  setCopied(false);
                  setCopyFailed(false);
                }}
              />
              <p className="text-muted-foreground text-xs">{labels.nameHint}</p>
            </>
          )}
          {binding.isPending && (
            <p role="status" className="text-muted-foreground text-xs">
              {labels.generating}
            </p>
          )}
          {binding.error && (
            <p role="alert" className="text-destructive text-xs">
              {labels.bindFailed}
            </p>
          )}
          {command && (
            <>
              <Input aria-label={labels.command} value={command} readOnly />
              {expiresAt !== null && (
                <p className="text-muted-foreground text-xs">
                  {fill(labels.expiresAt, {
                    time: new Intl.DateTimeFormat(locale, {
                      hour: "2-digit",
                      minute: "2-digit",
                    }).format(expiresAt),
                  })}
                </p>
              )}
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="w-fit"
                onClick={() => void copy()}
              >
                {copied ? labels.copied : labels.copy}
              </Button>
              {copyFailed && (
                <p role="alert" className="text-destructive text-xs">
                  {labels.copyFailed}
                </p>
              )}
            </>
          )}
          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              disabled={binding.isPending || (needsName && !groupName)}
              onClick={() =>
                binding.mutate({
                  targetProvider: provider,
                  groupName: needsName ? groupName : undefined,
                })
              }
            >
              {labels.newCode}
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => setVisible(false)}
            >
              {labels.close}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
