"use client";

import {
  CheckIcon,
  CopyIcon,
  LoaderCircleIcon,
  QrCodeIcon,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import type { ChannelProvider } from "@/core/channels/types";
import {
  useBindingCode,
  type PendingBindingCode,
} from "@/core/channels/use-binding-code";
import { useI18n } from "@/core/i18n/hooks";

export type PendingWechatBinding = PendingBindingCode;

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
  // Rescanning hands back the command already copied to the phone, so the
  // user is not sent through another copy/switch-app loop.
  const { stage, binding, command, copied, copyFailed, reportCopy, retry } =
    useBindingCode({
      provider: "wechat",
      alreadyConnected: provider.connection_status === "connected",
      bindingToResume,
    });

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(command);
      reportCopy(true);
    } catch {
      reportCopy(false);
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
            <Button type="button" variant="outline" onClick={retry}>
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
