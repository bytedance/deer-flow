"use client";

import { CheckIcon, CopyIcon, LoaderCircleIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { GatewayApiError } from "@/core/api/errors";
import { channelProviderName } from "@/core/channels/provider-state";
import type { ChannelProvider } from "@/core/channels/types";
import { useBindingCode } from "@/core/channels/use-binding-code";
import { writeTextToClipboard } from "@/core/clipboard";
import { useI18n } from "@/core/i18n/hooks";

import { ChannelProviderIcon } from "./channel-provider-icon";

/**
 * Connects an app whose bot links accounts with `/connect <code>` (Slack,
 * Discord, Feishu, …). The command stays on screen, copyable, until the bot
 * reports the binding or the code expires. A code is created when the dialog
 * opens and kept until it closes.
 */
export function ChannelBindingCodeDialog({
  provider,
  open,
  onOpenChange,
}: {
  provider: ChannelProvider | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  if (!provider) return null;
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[440px]">
        <ChannelBindingCode
          provider={provider}
          onDone={() => onOpenChange(false)}
        />
      </DialogContent>
    </Dialog>
  );
}

function ChannelBindingCode({
  provider,
  onDone,
}: {
  provider: ChannelProvider;
  onDone: () => void;
}) {
  const { t, locale } = useI18n();
  const text = t.channels.bindingCode;
  const name = channelProviderName(provider, t);
  const {
    stage,
    binding,
    command,
    error,
    copied,
    copyFailed,
    reportCopy,
    retry,
  } = useBindingCode({
    provider: provider.provider,
    alreadyConnected: provider.connection_status === "connected",
  });
  // The server caps unused codes per app; its English detail is not shown.
  const tooManyCodes = error instanceof GatewayApiError && error.status === 429;
  const errorDetail =
    error instanceof GatewayApiError && !tooManyCodes ? error.rawMessage : "";
  const expiresAt = binding
    ? new Intl.DateTimeFormat(locale, {
        hour: "2-digit",
        minute: "2-digit",
      }).format(binding.expiresAt)
    : "";

  const copy = async () => {
    reportCopy(await writeTextToClipboard(command));
  };

  return (
    <>
      <div className="flex items-center gap-3 pr-4">
        <div className="bg-muted flex size-11 shrink-0 items-center justify-center rounded-lg">
          <ChannelProviderIcon
            provider={provider.provider}
            className="size-7"
          />
        </div>
        <DialogHeader className="gap-1 text-left">
          <DialogTitle>{t.channels.setupTitle(name)}</DialogTitle>
          <DialogDescription>{text.description(name)}</DialogDescription>
        </DialogHeader>
      </div>
      <div
        role="status"
        aria-live="polite"
        className="flex min-h-40 flex-col justify-center gap-3 text-center"
      >
        {stage === "connected" ? (
          <>
            <div className="bg-secondary mx-auto rounded-full p-4">
              <CheckIcon className="size-8" />
            </div>
            <p className="font-medium">{text.connected(name)}</p>
          </>
        ) : stage === "binding" ? (
          <>
            <code className="bg-muted rounded-lg border p-3 text-sm break-all select-all">
              {command}
            </code>
            <Button type="button" variant="outline" onClick={() => void copy()}>
              {copied ? <CheckIcon /> : <CopyIcon />}
              {copied ? text.copied : text.copy}
            </Button>
            {copyFailed && (
              <p className="text-destructive text-xs">{text.copyFailed}</p>
            )}
            <p className="text-muted-foreground text-xs">
              {text.expiresAt(expiresAt)}
            </p>
            <p className="text-muted-foreground flex items-center justify-center gap-2 text-sm">
              <LoaderCircleIcon className="size-3.5 animate-spin" />
              {text.waiting(name)}
            </p>
          </>
        ) : stage === "loading" ? (
          <>
            <LoaderCircleIcon className="text-muted-foreground mx-auto size-5 animate-spin" />
            <p className="text-muted-foreground text-sm">{text.loading}</p>
          </>
        ) : stage === "expired" ? (
          <>
            <p className="text-muted-foreground text-sm">{text.expired}</p>
            <Button type="button" variant="outline" onClick={retry}>
              {text.newCode}
            </Button>
          </>
        ) : (
          <>
            <p className="text-muted-foreground text-sm">
              {tooManyCodes ? text.tooManyCodes : text.failed}
            </p>
            {errorDetail ? (
              <p className="text-muted-foreground text-xs break-words">
                {errorDetail}
              </p>
            ) : null}
            <Button type="button" variant="outline" onClick={retry}>
              {text.retry}
            </Button>
          </>
        )}
      </div>
      <Button
        type="button"
        variant={stage === "connected" ? "default" : "outline"}
        onClick={onDone}
      >
        {stage === "connected" ? text.done : t.common.close}
      </Button>
    </>
  );
}
