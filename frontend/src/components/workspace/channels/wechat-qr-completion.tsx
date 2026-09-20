"use client";

import { useQueryClient } from "@tanstack/react-query";
import {
  CheckIcon,
  CopyIcon,
  LoaderCircleIcon,
  QrCodeIcon,
} from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  connectChannelProvider,
  listChannelConnections,
  listChannelProviders,
} from "@/core/channels/api";
import {
  startConnectionPoll,
  type ConnectPollHandle,
} from "@/core/channels/connect-poll";
import {
  channelConnectionsQueryKey,
  channelProviderQueryKey,
} from "@/core/channels/hooks";
import type { ChannelProvider } from "@/core/channels/types";
import { useI18n } from "@/core/i18n/hooks";

export type PendingWechatBinding = {
  code: string;
  expiresAt: number;
};

/** Keep credential setup and user identity binding visible as separate steps. */
export function WechatQRCompletion({
  provider,
  onDone,
  onRestart,
  bindingToResume,
}: {
  provider: ChannelProvider;
  onDone: () => void;
  onRestart: (binding: PendingWechatBinding | null) => void;
  bindingToResume?: PendingWechatBinding | null;
}) {
  const { t } = useI18n();
  const text = t.channels.wechatQr;
  const queryClient = useQueryClient();
  const alreadyConnected = provider.connection_status === "connected";
  const [stage, setStage] = useState<
    "loading" | "binding" | "connected" | "error" | "expired"
  >(alreadyConnected ? "connected" : "loading");
  const [attempt, setAttempt] = useState(0);
  const [binding, setBinding] = useState<PendingWechatBinding | null>(null);
  const command = binding ? `/connect ${binding.code}` : "";
  const [copied, setCopied] = useState(false);
  const [copyFailed, setCopyFailed] = useState(false);

  useEffect(() => {
    if (alreadyConnected) {
      setStage("connected");
      return;
    }
    let stopped = false;
    let poller: ConnectPollHandle | undefined;
    let expiry: ReturnType<typeof setTimeout> | undefined;
    setStage("loading");
    setCopied(false);
    setCopyFailed(false);
    const connected = () => {
      if (stopped) return;
      clearTimeout(expiry);
      setStage("connected");
      void queryClient.invalidateQueries({ queryKey: channelProviderQueryKey });
      void queryClient.invalidateQueries({
        queryKey: channelConnectionsQueryKey,
      });
    };
    const start = setTimeout(() => {
      void (async () => {
        // Runtime setup's response does not include existing user bindings.
        const current = await queryClient.fetchQuery({
          queryKey: channelProviderQueryKey,
          queryFn: listChannelProviders,
          staleTime: 0,
        });
        if (stopped) return;
        if (
          current.providers.some(
            (item) =>
              item.provider === "wechat" &&
              item.connection_status === "connected",
          )
        ) {
          connected();
          return;
        }
        // Keep the command already copied to the phone, with its original
        // deadline. Rescanning must not create another copy/switch-app loop.
        let nextBinding = bindingToResume;
        if (!nextBinding || nextBinding.expiresAt <= Date.now()) {
          const result = await connectChannelProvider("wechat");
          const lifetime =
            Number.isFinite(result.expires_in) && result.expires_in > 0
              ? result.expires_in
              : 600;
          nextBinding = {
            code: result.code,
            expiresAt: Date.now() + lifetime * 1000,
          };
        }
        if (stopped) return;
        setBinding(nextBinding);
        const expiresIn = (nextBinding.expiresAt - Date.now()) / 1000;
        if (expiresIn <= 0) {
          setStage("expired");
          return;
        }
        setStage("binding");
        expiry = setTimeout(() => {
          poller?.cancel();
          if (!stopped) setStage("expired");
        }, expiresIn * 1000);
        poller = startConnectionPoll({
          provider: "wechat",
          expiresInSeconds: expiresIn,
          fetchConnections: () =>
            queryClient.fetchQuery({
              queryKey: channelConnectionsQueryKey,
              queryFn: listChannelConnections,
              staleTime: 0,
            }),
          onConnected: connected,
        });
      })().catch(() => {
        if (!stopped) setStage("error");
      });
    }, 0);
    return () => {
      stopped = true;
      clearTimeout(start);
      clearTimeout(expiry);
      poller?.cancel();
    };
  }, [alreadyConnected, attempt, bindingToResume, queryClient]);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(command);
      setCopied(true);
      setCopyFailed(false);
    } catch {
      setCopyFailed(true);
    }
  };

  return (
    <div className="flex min-h-[328px] flex-col gap-5">
      <div className="flex items-start gap-3 rounded-xl bg-emerald-500/5 p-4">
        <span className="rounded-full bg-emerald-500/10 p-1.5 text-emerald-600">
          <CheckIcon className="size-4" />
        </span>
        <div className="space-y-1">
          <p className="text-sm font-medium">{text.saved}</p>
          <p className="text-muted-foreground text-xs leading-relaxed">
            {text.savedDescription}
          </p>
        </div>
      </div>
      <div
        role="status"
        aria-live="polite"
        className="flex flex-1 flex-col justify-center gap-3 text-center"
      >
        {stage === "connected" ? (
          <>
            <div className="mx-auto rounded-full bg-emerald-500/10 p-4 text-emerald-600">
              <CheckIcon className="size-8" />
            </div>
            <p className="font-medium">{text.connectedTitle}</p>
            <p className="text-muted-foreground text-sm">
              {text.connectedDescription}
            </p>
          </>
        ) : stage === "binding" ? (
          <>
            <p className="text-sm font-medium">{text.bindTitle}</p>
            <p className="text-muted-foreground text-xs leading-relaxed">
              {text.bindDescription}
            </p>
            <code className="bg-muted rounded-lg border p-3 text-sm break-all select-all">
              {command}
            </code>
            <Button type="button" variant="outline" onClick={() => void copy()}>
              {copied ? <CheckIcon /> : <CopyIcon />}
              {copied ? text.copied : text.copyCommand}
            </Button>
            {copyFailed && (
              <p className="text-destructive text-xs">{text.copyFailed}</p>
            )}
            <p className="text-muted-foreground flex items-center justify-center gap-2 text-xs">
              <LoaderCircleIcon className="size-3 animate-spin" />
              {text.bindWaiting}
            </p>
          </>
        ) : stage === "loading" ? (
          <>
            <LoaderCircleIcon className="mx-auto size-5 animate-spin" />
            <p className="text-muted-foreground text-sm">{text.bindLoading}</p>
          </>
        ) : (
          <>
            <p className="text-muted-foreground text-sm">
              {stage === "expired" ? text.bindExpired : text.bindFailed}
            </p>
            <Button
              type="button"
              variant="outline"
              onClick={() => setAttempt((value) => value + 1)}
            >
              {text.bindRetry}
            </Button>
          </>
        )}
      </div>
      {stage !== "connected" && (
        <div className="space-y-2 border-t pt-3 text-center">
          <p className="text-muted-foreground text-xs leading-relaxed">
            {text.restartHint}
          </p>
          <Button
            type="button"
            variant="secondary"
            className="w-full"
            onClick={() => onRestart(binding ?? bindingToResume ?? null)}
          >
            <QrCodeIcon />
            {text.restart}
          </Button>
          {stage === "binding" && (
            <p className="text-muted-foreground text-xs leading-relaxed">
              {text.restartKeepCommand}
            </p>
          )}
        </div>
      )}
      <Button
        type="button"
        variant={stage === "connected" ? "default" : "outline"}
        onClick={onDone}
      >
        {stage === "connected" ? text.done : t.common.close}
      </Button>
    </div>
  );
}
