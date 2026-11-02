import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import {
  connectChannelProvider,
  listChannelConnections,
  listChannelProviders,
} from "./api";
import { startConnectionPoll, type ConnectPollHandle } from "./connect-poll";
import { channelConnectionsQueryKey, channelProviderQueryKey } from "./hooks";
import type { ChannelProviderId } from "./types";

/** A binding code shown to the user, with the moment it stops working. */
export type PendingBindingCode = {
  code: string;
  expiresAt: number;
};

export type BindingCodeStage =
  | "loading"
  | "binding"
  | "connected"
  | "error"
  | "expired";

// The backend's code lifetime, for a response that omits or garbles `expires_in`.
const DEFAULT_CODE_LIFETIME_S = 600;

/**
 * Link the signed-in user to a provider whose bot accepts `/connect <code>`:
 * reuse a code the user may already have copied or mint one, keep it on screen
 * until it expires, and poll until the bot reports the binding. Unmounting
 * stops the poll; `retry` starts over.
 */
export function useBindingCode({
  provider,
  alreadyConnected = false,
  bindingToResume,
}: {
  provider: ChannelProviderId;
  /** The provider already reports a connection, so no code is needed. */
  alreadyConnected?: boolean;
  /** Reused until its original deadline instead of minting another code. */
  bindingToResume?: PendingBindingCode | null;
}) {
  const queryClient = useQueryClient();
  const [stage, setStage] = useState<BindingCodeStage>(
    alreadyConnected ? "connected" : "loading",
  );
  const [attempt, setAttempt] = useState(0);
  const [binding, setBinding] = useState<PendingBindingCode | null>(null);
  const [error, setError] = useState<unknown>(null);
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
    setError(null);
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
    // Defer one tick so Strict Mode's setup/cleanup probe cannot mint a
    // second code.
    const start = setTimeout(() => {
      void (async () => {
        // The caller's provider can be stale (a runtime-setup response does
        // not include existing user bindings), so check before minting.
        const current = await queryClient.fetchQuery({
          queryKey: channelProviderQueryKey,
          queryFn: listChannelProviders,
          staleTime: 0,
        });
        if (stopped) return;
        if (
          current.providers.some(
            (item) =>
              item.provider === provider &&
              item.connection_status === "connected",
          )
        ) {
          connected();
          return;
        }
        // Keep a command the user may already have copied, with its original
        // deadline, instead of sending them back for another one.
        let nextBinding = bindingToResume;
        if (!nextBinding || nextBinding.expiresAt <= Date.now()) {
          const result = await connectChannelProvider(provider);
          const lifetime =
            Number.isFinite(result.expires_in) && result.expires_in > 0
              ? result.expires_in
              : DEFAULT_CODE_LIFETIME_S;
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
          provider,
          expiresInSeconds: expiresIn,
          fetchConnections: () =>
            queryClient.fetchQuery({
              queryKey: channelConnectionsQueryKey,
              queryFn: listChannelConnections,
              staleTime: 0,
            }),
          onConnected: connected,
        });
      })().catch((reason: unknown) => {
        if (stopped) return;
        setError(reason);
        setStage("error");
      });
    }, 0);
    return () => {
      stopped = true;
      clearTimeout(start);
      clearTimeout(expiry);
      poller?.cancel();
    };
  }, [alreadyConnected, attempt, bindingToResume, provider, queryClient]);

  return {
    stage,
    /** The latest code shown; kept after expiry so a restart can hand it back. */
    binding,
    command: binding ? `/connect ${binding.code}` : "",
    /** Why the last attempt failed, while `stage` is "error". */
    error,
    copied,
    copyFailed,
    /** Record a clipboard write of `command`; every attempt starts uncopied. */
    reportCopy: (ok: boolean) => {
      if (ok) {
        setCopied(true);
        setCopyFailed(false);
      } else {
        setCopyFailed(true);
      }
    },
    /** Start a new attempt: reuse `bindingToResume` if still valid, else mint. */
    retry: () => setAttempt((value) => value + 1),
  };
}
