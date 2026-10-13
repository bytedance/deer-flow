"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { connectChannelProvider } from "@/core/channels/api";
import { channelConnectionsQueryKey } from "@/core/channels/hooks";
import { useI18n } from "@/core/i18n/hooks";

import { fill } from "./shared";

/** Group binding needs its own command; a connected private chat is not completion. */
export function BindFeishuGroup() {
  const { t, locale } = useI18n();
  const labels = t.scheduledTasks.notificationGroup;
  const queryClient = useQueryClient();
  const [visible, setVisible] = useState(false);
  const [copied, setCopied] = useState(false);
  const [copyFailed, setCopyFailed] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [expiresAt, setExpiresAt] = useState<number | null>(null);
  const binding = useMutation({
    mutationFn: () => connectChannelProvider("feishu"),
    onSuccess: (result) => {
      setCopied(false);
      setCopyFailed(false);
      setExpiresAt(Date.now() + result.expires_in * 1000);
    },
  });
  const command = binding.data ? `/connect ${binding.data.code}` : "";
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
          onClick={() => {
            setVisible(true);
            if (!binding.data) binding.mutate();
          }}
        >
          {labels.bind}
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
              disabled={binding.isPending}
              onClick={() => binding.mutate()}
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
