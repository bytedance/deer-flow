"use client";

import { useQueryClient } from "@tanstack/react-query";
import {
  CheckIcon,
  CircleAlertIcon,
  LoaderCircleIcon,
  RefreshCwIcon,
  SmartphoneIcon,
} from "lucide-react";
import { QRCodeSVG } from "qrcode.react";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  cancelWechatQRLogin,
  pollWechatQRLogin,
  startWechatQRLogin,
} from "@/core/channels/api";
import type {
  ChannelProvider,
  WechatQRLoginSession,
} from "@/core/channels/types";
import { useI18n } from "@/core/i18n/hooks";

export function WechatQRLogin({
  onConfigured,
}: {
  onConfigured: (provider: ChannelProvider) => void;
}) {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [attempt, setAttempt] = useState(0);
  const [session, setSession] = useState<WechatQRLoginSession | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [verifyCode, setVerifyCode] = useState("");
  const [verifying, setVerifying] = useState(false);
  const submitCodeRef = useRef<(code: string) => void>(() => undefined);
  const onConfiguredRef = useRef(onConfigured);
  useEffect(() => {
    onConfiguredRef.current = onConfigured;
  }, [onConfigured]);

  useEffect(() => {
    let stopped = false;
    let polling = false;
    let sessionId: string | undefined;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let expiryTimer: ReturnType<typeof setTimeout> | undefined;
    const controller = new AbortController();
    setSession(null);
    setError(null);
    setVerifyCode("");
    setVerifying(false);

    const cancel = (id: string) => {
      void cancelWechatQRLogin(id).catch(() => undefined);
    };
    const poll = async (code?: string) => {
      if (stopped || !sessionId) return;
      polling = true;
      try {
        const result = await pollWechatQRLogin(
          sessionId,
          controller.signal,
          code,
        );
        if (stopped) return;
        setSession(result);
        setVerifying(false);
        if (result.status === "confirmed" && result.provider) {
          void queryClient.invalidateQueries({
            queryKey: ["channelProviders"],
          });
          void queryClient.invalidateQueries({
            queryKey: ["channelConnections"],
          });
          onConfiguredRef.current(result.provider);
        } else if (
          result.status === "pending" ||
          result.status === "scanned" ||
          (result.status === "verification_required" &&
            result.error === "network")
        ) {
          timer = setTimeout(() => {
            void poll();
          }, 1500);
        }
      } catch (error) {
        if (!stopped && !controller.signal.aborted) {
          setVerifying(false);
          setError(error instanceof Error ? error.message : "");
        }
      } finally {
        polling = false;
      }
    };

    submitCodeRef.current = (code) => {
      setVerifying(true);
      setVerifyCode("");
      clearTimeout(timer);
      void poll(code);
    };

    // Defer one tick so Strict Mode's setup/cleanup probe cannot start a
    // second server session and invalidate the QR the user is scanning.
    const startTimer = setTimeout(() => {
      // Let a pending start finish so its session can still be cancelled if the
      // dialog was closed before the server returned its ID.
      void startWechatQRLogin()
        .then((result) => {
          if (stopped) {
            cancel(result.id);
            return;
          }
          sessionId = result.id;
          expiryTimer = setTimeout(() => {
            // Let an in-flight confirmation finish saving credentials. The
            // server also checks expiry before applying a polling response.
            if (stopped || polling) return;
            controller.abort();
            clearTimeout(timer);
            setVerifying(false);
            setSession((current) =>
              current && current.status !== "confirmed"
                ? { ...current, status: "expired", error: null }
                : current,
            );
          }, result.expires_in * 1000);
          setSession(result);
          timer = setTimeout(() => {
            void poll();
          }, 1500);
        })
        .catch((error: unknown) => {
          if (!stopped) setError(error instanceof Error ? error.message : "");
        });
    }, 0);

    return () => {
      stopped = true;
      controller.abort();
      clearTimeout(timer);
      clearTimeout(startTimer);
      clearTimeout(expiryTimer);
      submitCodeRef.current = () => undefined;
      if (sessionId) cancel(sessionId);
    };
  }, [attempt, queryClient]);

  const verificationRequired = session?.status === "verification_required";
  const ended =
    session?.status === "expired" ||
    session?.status === "failed" ||
    error !== null;
  const scanned =
    session?.status === "scanned" || session?.status === "confirmed";
  const title = ended
    ? session?.status === "expired"
      ? t.channels.wechatQr.expiredTitle
      : t.channels.wechatQr.failedTitle
    : verificationRequired
      ? t.channels.wechatQr.verifyTitle
      : scanned
        ? t.channels.wechatQr.scannedTitle
        : session
          ? t.channels.wechatQr.waiting
          : t.channels.wechatQr.loading;
  const description =
    (error === "" ? null : error) ??
    (session?.error ? t.channels.wechatQr[session.error] : null) ??
    (verificationRequired ? t.channels.wechatQr.verifyDescription : null) ??
    (session?.status === "expired"
      ? t.channels.wechatQr.expired
      : session?.status === "failed" || error !== null
        ? t.channels.wechatQr.failed
        : session?.status === "scanned"
          ? t.channels.wechatQr.scanned
          : session?.status === "confirmed"
            ? t.channels.wechatQr.confirmed
            : t.channels.wechatQr.scan);

  return (
    <div className="flex min-h-[328px] flex-col items-center gap-4">
      <div className="relative flex size-[232px] shrink-0 items-center justify-center overflow-hidden rounded-2xl border bg-white p-3 shadow-xs">
        {session && !ended && !scanned && !verificationRequired ? (
          <QRCodeSVG
            value={session.qrcode_content}
            size={208}
            marginSize={4}
            level="M"
            title={t.channels.wechatQr.imageTitle}
          />
        ) : null}
        {ended ? (
          <div className="flex h-full w-full flex-col items-center justify-center gap-4 rounded-lg bg-neutral-50 text-neutral-600">
            <CircleAlertIcon
              className="size-8 stroke-[1.5]"
              aria-hidden="true"
            />
            <Button
              type="button"
              variant="outline"
              className="bg-white text-neutral-900"
              onClick={() => setAttempt((value) => value + 1)}
            >
              <RefreshCwIcon />
              {t.channels.wechatQr.retry}
            </Button>
          </div>
        ) : verificationRequired ? (
          <div className="flex w-full flex-col gap-3 text-neutral-900">
            <SmartphoneIcon className="mx-auto size-8 text-emerald-600" />
            <label
              htmlFor="wechat-pairing-code"
              className="text-center text-sm font-medium"
            >
              {t.channels.wechatQr.verifyLabel}
            </label>
            <Input
              id="wechat-pairing-code"
              inputMode="numeric"
              autoComplete="one-time-code"
              maxLength={16}
              value={verifyCode}
              disabled={verifying}
              className="text-center font-mono tracking-widest"
              onChange={(event) =>
                setVerifyCode(event.target.value.replace(/[^0-9]/g, ""))
              }
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  if (verifyCode && !verifying)
                    submitCodeRef.current(verifyCode);
                }
              }}
            />
            <Button
              type="button"
              disabled={!verifyCode || verifying}
              onClick={() => submitCodeRef.current(verifyCode)}
            >
              {verifying
                ? t.channels.wechatQr.verifying
                : t.channels.wechatQr.verifySubmit}
            </Button>
          </div>
        ) : scanned ? (
          <div className="flex flex-col items-center gap-3 text-emerald-600">
            <div className="relative rounded-full bg-emerald-50 p-5">
              <SmartphoneIcon className="size-10 stroke-[1.5]" />
              <span className="absolute -right-1 bottom-0 rounded-full bg-emerald-600 p-1 text-white">
                <CheckIcon className="size-4" />
              </span>
            </div>
          </div>
        ) : !session ? (
          <LoaderCircleIcon
            className="size-6 animate-spin text-neutral-400"
            aria-label={t.channels.wechatQr.loading}
          />
        ) : null}
      </div>
      <div
        role="status"
        aria-live="polite"
        className="w-full space-y-1.5 text-center"
      >
        <p className="flex items-center justify-center gap-2 text-sm font-medium">
          {session && !ended ? (
            <span
              className="size-1.5 rounded-full bg-emerald-500"
              aria-hidden="true"
            />
          ) : null}
          {title}
        </p>
        <p className="text-muted-foreground mx-auto max-w-[300px] text-xs leading-relaxed break-words">
          {description}
        </p>
        {!ended && (
          <p className="text-muted-foreground text-xs">
            {t.channels.wechatQr.autoSave}
          </p>
        )}
      </div>
    </div>
  );
}
