"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { browserStreamURL } from "./api";

export interface BrowserTab {
  index: number;
  title: string;
  url: string;
  active: boolean;
}

export type BrowserInputEvent =
  | { type: "click"; nx: number; ny: number }
  | { type: "move"; nx: number; ny: number }
  | { type: "down"; nx: number; ny: number }
  | { type: "up"; nx: number; ny: number }
  | { type: "wheel"; dx: number; dy: number; nx?: number; ny?: number }
  | { type: "key"; key: string }
  | { type: "text"; text: string }
  | { type: "navigate"; url: string }
  | { type: "back" }
  | { type: "forward" }
  | { type: "activate_tab"; index: number };

export type BrowserStreamStatus = "idle" | "connecting" | "open" | "closed";

const RECONNECT_BASE_DELAY_MS = 800;
const RECONNECT_MAX_DELAY_MS = 10_000;
const RECONNECT_MAX_ATTEMPTS = 6;

function normalizeSeedUrl(url: string | null | undefined): string {
  return (url ?? "").split("#", 1)[0]?.replace(/\/+$/, "") ?? "";
}

/**
 * Manage a live browser screencast WebSocket.
 *
 * When ``enabled`` is true, opens the stream, exposes the latest JPEG frame as
 * a data URL, and returns a ``sendInput`` callback that forwards user input to
 * the live page. Closes and cleans up when disabled or unmounted.
 *
 * ``seedUrl`` is only read when a connection is first established (via a ref, so
 * it is NOT a reconnect trigger). A separate effect steers an already-open live
 * page toward a changed seed with an in-band ``navigate`` event, so ordinary
 * navigations no longer tear down and rebuild the socket.
 */
export function useBrowserStream(
  threadId: string,
  enabled: boolean,
  seedUrl?: string,
  onNavRejected?: (
    url: string | undefined,
    message: string | undefined,
  ) => void,
) {
  const [status, setStatus] = useState<BrowserStreamStatus>("idle");
  const [frameUrl, setFrameUrl] = useState<string | null>(null);
  const [liveUrl, setLiveUrl] = useState<string | null>(null);
  const [tabs, setTabs] = useState<BrowserTab[]>([]);
  const [connectionAttempt, setConnectionAttempt] = useState(0);
  const socketRef = useRef<WebSocket | null>(null);
  const pendingNavigateRef = useRef<Extract<
    BrowserInputEvent,
    { type: "navigate" }
  > | null>(null);
  // Read the seed at connect time only; it must not be a reconnect dependency.
  const seedRef = useRef(seedUrl);
  seedRef.current = seedUrl;
  // Latest live page URL reported by the server, used to decide whether an
  // open stream already shows the seed target (avoids redundant navigations).
  const liveUrlRef = useRef<string | null>(null);
  const onNavRejectedRef = useRef(onNavRejected);
  onNavRejectedRef.current = onNavRejected;

  const sendInput = useCallback((event: BrowserInputEvent) => {
    const socket = socketRef.current;
    if (socket?.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify(event));
      return true;
    }
    // URL bar submissions are user intent and must not be lost during the
    // short Live connection window right after opening the panel.
    if (event.type === "navigate") {
      pendingNavigateRef.current = event;
    }
    return false;
  }, []);

  useEffect(() => {
    pendingNavigateRef.current = null;
  }, [threadId]);

  useEffect(() => {
    if (enabled) {
      return;
    }
    setConnectionAttempt(0);
    setFrameUrl(null);
    setLiveUrl(null);
    setTabs([]);
    liveUrlRef.current = null;
  }, [enabled, threadId]);

  useEffect(() => {
    if (!enabled) {
      setStatus("idle");
      liveUrlRef.current = null;
      return;
    }

    let closedByEffect = false;
    let reconnectTimer: number | null = null;
    setStatus("connecting");
    // browserStreamURL treats empty/undefined seed identically (no seed param),
    // so the raw ref value is fine here. Record the seed optimistically so the
    // "steer to seed" effect below does not fire a duplicate navigate right
    // after open (the server already aligns the page to the connect-time seed).
    liveUrlRef.current = seedRef.current ?? null;
    const socket = new WebSocket(browserStreamURL(threadId, seedRef.current));
    socketRef.current = socket;

    const scheduleReconnect = () => {
      if (closedByEffect || !enabled) {
        return;
      }
      if (reconnectTimer !== null) {
        return;
      }
      // Exponential backoff with a ceiling + attempt cap so a server that keeps
      // rejecting the upgrade cannot pin the client in a tight reconnect loop.
      if (connectionAttempt >= RECONNECT_MAX_ATTEMPTS) {
        return;
      }
      const delay = Math.min(
        RECONNECT_BASE_DELAY_MS * 2 ** connectionAttempt,
        RECONNECT_MAX_DELAY_MS,
      );
      reconnectTimer = window.setTimeout(() => {
        setConnectionAttempt((attempt) => attempt + 1);
      }, delay);
    };

    socket.onopen = () => {
      const pendingNavigate = pendingNavigateRef.current;
      if (pendingNavigate) {
        socket.send(JSON.stringify(pendingNavigate));
        pendingNavigateRef.current = null;
      }
      // Reset the reconnect budget on a successful open. Without this the
      // cumulative attempt counter never returns to 0 while the panel stays
      // mounted, so after RECONNECT_MAX_ATTEMPTS total reconnects — even across
      // many healthy connections — scheduleReconnect would bail forever and
      // Live would go permanently dead until the panel is toggled off/on.
      setConnectionAttempt(0);
      setStatus("open");
    };
    socket.onmessage = async (message) => {
      try {
        const raw =
          typeof message.data === "string"
            ? message.data
            : message.data instanceof Blob
              ? await message.data.text()
              : message.data instanceof ArrayBuffer
                ? new TextDecoder().decode(message.data)
                : String(message.data);
        // The message may resolve after cleanup (async Blob/ArrayBuffer decode);
        // do not write state for a socket the effect already tore down.
        if (closedByEffect) {
          return;
        }
        const payload = JSON.parse(raw) as {
          type?: string;
          data?: string;
          url?: string;
          message?: string;
          tabs?: BrowserTab[];
        };
        if (payload.type === "frame" && payload.data) {
          setFrameUrl(`data:image/jpeg;base64,${payload.data}`);
        } else if (payload.type === "url" && payload.url) {
          liveUrlRef.current = payload.url;
          setLiveUrl(payload.url);
        } else if (payload.type === "tabs" && Array.isArray(payload.tabs)) {
          setTabs(payload.tabs);
        } else if (payload.type === "nav_rejected") {
          onNavRejectedRef.current?.(payload.url, payload.message);
        }
      } catch (error) {
        console.warn("Ignoring malformed browser stream message", error);
      }
    };
    socket.onclose = () => {
      if (!closedByEffect) {
        setStatus("closed");
        scheduleReconnect();
      }
    };
    socket.onerror = () => {
      if (!closedByEffect) {
        setStatus("closed");
        scheduleReconnect();
      }
    };

    return () => {
      closedByEffect = true;
      if (reconnectTimer !== null) {
        window.clearTimeout(reconnectTimer);
      }
      socketRef.current = null;
      socket.close();
    };
  }, [connectionAttempt, enabled, threadId]);

  // Steer an already-open stream toward a changed seed in-band instead of
  // rebuilding the socket. Only navigates when the live page differs from the
  // seed target, so redirects/history moves the server already reflects do not
  // cause a redundant navigation loop.
  useEffect(() => {
    if (!enabled || status !== "open") {
      return;
    }
    const target = seedUrl?.trim();
    if (!target) {
      return;
    }
    if (normalizeSeedUrl(target) === normalizeSeedUrl(liveUrlRef.current)) {
      return;
    }
    sendInput({ type: "navigate", url: target });
  }, [enabled, seedUrl, sendInput, status]);

  return { status, frameUrl, liveUrl, tabs, sendInput };
}
