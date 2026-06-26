"use client";

import { setEhmCookies } from "./ehm-auth";

const AI_READY_MESSAGE = { type: "AI_READY" } as const;
const AI_REQUEST_USER_MESSAGE = { type: "AI_REQUEST_USER" } as const;
const AI_PING = "AI_PING";
const AI_INIT = "AI_INIT";
const AI_TOKEN_REFRESH = "AI_TOKEN_REFRESH";
const MAX_HOST_TOKEN_AGE_MS = 24 * 60 * 60 * 1000;
const HOST_TOKEN_REQUEST_TIMEOUT_MS = 5000;
const HOST_BRIDGE_LOG_PREFIX = "[EHM Host Bridge]";

type HostBridgePayload = {
  type?: string;
  ehmToken?: unknown;
  ehmUser?: unknown;
  issuedAt?: unknown;
  token?: {
    accessToken?: unknown;
    userId?: unknown;
    orgId?: unknown;
    username?: unknown;
    nickname?: unknown;
  };
};

function parseMessageData(data: unknown): HostBridgePayload | null {
  if (!data) return null;
  if (typeof data === "string") {
    try {
      return JSON.parse(data) as HostBridgePayload;
    } catch {
      return null;
    }
  }
  if (typeof data === "object") {
    return data as HostBridgePayload;
  }
  return null;
}

function normalizeIssuedAt(raw: unknown): number {
  return typeof raw === "number" && Number.isFinite(raw) ? raw : 0;
}

function normalizeToken(raw: unknown): string {
  return typeof raw === "string" ? raw.trim() : "";
}

async function reauthenticateWithEhmToken(token: string): Promise<boolean> {
  if (!token) return false;
  try {
    const res = await window.fetch("/api/v1/auth/ins-base/authenticate", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
      },
      credentials: "include",
    });
    return res.ok;
  } catch {
    return false;
  }
}

function postToParent(message: Record<string, unknown>) {
  if (typeof window === "undefined") return;
  if (window.parent === window) return;
  try {
    window.parent.postMessage(JSON.stringify(message), "*");
  } catch {
    // ignore
  }
}

let latestIssuedAt = 0;
let started = false;
let hostBridgeCleanup: (() => void) | null = null;
let pendingHostTokenResolver: ((received: boolean) => void) | null = null;
let pendingHostTokenTimeout: ReturnType<typeof setTimeout> | null = null;

function resolveLoginRecoveryTarget(): string {
  if (typeof window === "undefined") return "/workspace";
  const params = new URLSearchParams(window.location.search);
  const next = params.get("next");
  if (
    typeof next === "string" &&
    next.startsWith("/") &&
    !next.startsWith("//")
  ) {
    return next;
  }
  return "/workspace";
}

async function handleTokenRefresh(payload: HostBridgePayload) {
  const ehmToken =
    normalizeToken(payload.ehmToken) ||
    normalizeToken(payload.token?.accessToken);
  const ehmUser = normalizeToken(payload.ehmUser);
  const issuedAt = normalizeIssuedAt(payload.issuedAt) || Date.now();

  if (!ehmToken) return;
  if (issuedAt < latestIssuedAt) return;
  if (issuedAt - latestIssuedAt > MAX_HOST_TOKEN_AGE_MS) return;

  latestIssuedAt = issuedAt;
  setEhmCookies(ehmToken, ehmUser || undefined);
  console.info(HOST_BRIDGE_LOG_PREFIX, "received AI_TOKEN_REFRESH", {
    issuedAt,
    path: window.location.pathname,
  });
  const authenticated = await reauthenticateWithEhmToken(ehmToken);
  console.info(HOST_BRIDGE_LOG_PREFIX, "reauthenticate result", {
    authenticated,
    path: window.location.pathname,
  });
  if (pendingHostTokenResolver) {
    pendingHostTokenResolver(authenticated);
    pendingHostTokenResolver = null;
  }
  if (pendingHostTokenTimeout) {
    clearTimeout(pendingHostTokenTimeout);
    pendingHostTokenTimeout = null;
  }
  if (authenticated && window.location.pathname === "/login") {
    const target = resolveLoginRecoveryTarget();
    console.info(HOST_BRIDGE_LOG_PREFIX, "recovering from login", { target });
    window.location.replace(target);
  }
}

function handleInit(payload: HostBridgePayload) {
  const ehmToken = normalizeToken(payload.token?.accessToken);
  if (!ehmToken) return;
  const ehmUser = normalizeToken(payload.ehmUser);
  const issuedAt = Date.now();
  void handleTokenRefresh({
    type: AI_TOKEN_REFRESH,
    ehmToken,
    ehmUser,
    issuedAt,
  });
}

export function requestFreshHostToken(): Promise<boolean> {
  if (typeof window === "undefined" || window.parent === window) {
    return Promise.resolve(false);
  }

  if (pendingHostTokenTimeout) {
    clearTimeout(pendingHostTokenTimeout);
    pendingHostTokenTimeout = null;
  }

  return new Promise(resolve => {
    pendingHostTokenResolver = resolve;
    pendingHostTokenTimeout = setTimeout(() => {
      console.warn(HOST_BRIDGE_LOG_PREFIX, "AI_REQUEST_USER timed out", {
        timeoutMs: HOST_TOKEN_REQUEST_TIMEOUT_MS,
        path: window.location.pathname,
      });
      pendingHostTokenResolver = null;
      pendingHostTokenTimeout = null;
      resolve(false);
    }, HOST_TOKEN_REQUEST_TIMEOUT_MS);
    console.info(HOST_BRIDGE_LOG_PREFIX, "requesting fresh host token", {
      path: window.location.pathname,
      timeoutMs: HOST_TOKEN_REQUEST_TIMEOUT_MS,
    });
    postToParent(AI_REQUEST_USER_MESSAGE);
  });
}

export function startEhmHostBridge() {
  if (typeof window === "undefined") return () => {};
  if (started) return hostBridgeCleanup || (() => {});
  started = true;

  const onMessage = (event: MessageEvent) => {
    if (event.source !== window.parent) return;
    const payload = parseMessageData(event.data);
    if (!payload?.type) return;

    if (payload.type === AI_PING) {
      postToParent(AI_READY_MESSAGE);
      return;
    }

    if (payload.type === AI_INIT) {
      postToParent(AI_READY_MESSAGE);
      handleInit(payload);
      return;
    }

    if (payload.type === AI_TOKEN_REFRESH) {
      console.info(HOST_BRIDGE_LOG_PREFIX, "message AI_TOKEN_REFRESH received", {
        path: window.location.pathname,
      });
      void handleTokenRefresh(payload);
    }
  };

  window.addEventListener("message", onMessage);
  console.info(HOST_BRIDGE_LOG_PREFIX, "bridge started", {
    path: window.location.pathname,
  });
  postToParent(AI_READY_MESSAGE);
  postToParent(AI_REQUEST_USER_MESSAGE);

  hostBridgeCleanup = () => {
    window.removeEventListener("message", onMessage);
    if (pendingHostTokenTimeout) {
      clearTimeout(pendingHostTokenTimeout);
      pendingHostTokenTimeout = null;
    }
    if (pendingHostTokenResolver) {
      pendingHostTokenResolver(false);
      pendingHostTokenResolver = null;
    }
    started = false;
    hostBridgeCleanup = null;
  };
  return hostBridgeCleanup;
}
