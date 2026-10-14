"use client";

import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";

import { QueryClientProvider } from "@/components/query-client-provider";
import { useOptionalAuthUserId } from "@/core/auth/AuthProvider";
import { isStaticWebsiteOnly } from "@/core/static-mode";

import {
  AUTHENTICATION_REQUIRED,
  WorkspaceSession,
  type WorkspaceLifetime,
  type WorkspaceState,
} from "./session";

export interface WorkspaceContextValue {
  readonly state: WorkspaceState;
  readonly select: (workspaceId?: string) => Promise<boolean>;
  readonly refresh: () => Promise<boolean>;
}
const WorkspaceContext = createContext<WorkspaceContextValue | null>(null);
const unavailable: WorkspaceContextValue = Object.freeze({
  state: AUTHENTICATION_REQUIRED,
  select: async () => false,
  refresh: async () => false,
});

function ActorWorkspaceProvider({
  actorUserId,
  children,
}: {
  actorUserId: string;
  children: ReactNode;
}) {
  const [session] = useState(() => new WorkspaceSession(actorUserId));
  const state = useSyncExternalStore(
    session.subscribe,
    session.getSnapshot,
    session.getServerSnapshot,
  );
  useEffect(() => session.acquire(), [session]);
  const value = useMemo(
    () => ({ state, select: session.select, refresh: session.refresh }),
    [state, session],
  );
  return (
    <WorkspaceContext.Provider value={value}>
      {children}
    </WorkspaceContext.Provider>
  );
}

/** Enabled must come from the server capability, never browser storage. */
export function WorkspaceProvider({
  enabled = false,
  children,
}: {
  enabled?: boolean;
  children: ReactNode;
}) {
  const actorUserId = useOptionalAuthUserId();
  if (!enabled || isStaticWebsiteOnly()) return children;
  if (!actorUserId)
    return (
      <WorkspaceContext.Provider value={unavailable}>
        {children}
      </WorkspaceContext.Provider>
    );
  return (
    <ActorWorkspaceProvider key={actorUserId} actorUserId={actorUserId}>
      {children}
    </ActorWorkspaceProvider>
  );
}

/** Controls may read this during loading; content belongs under the boundary. */
export function useWorkspaceContext() {
  return useContext(WorkspaceContext);
}

export function useWorkspaceLifetime(): WorkspaceLifetime | null {
  const context = useWorkspaceContext();
  if (!context) return null;
  if (context.state.status !== "ready" || !context.state.active)
    throw new Error("Workspace content requires a confirmed lifetime");
  return context.state.active;
}

/** A pending/denied workspace must never fall back to unscoped content reads. */
export function WorkspaceReadyBoundary({
  children,
  fallback = null,
}: {
  children: ReactNode;
  fallback?: ReactNode;
}) {
  const context = useWorkspaceContext();
  if (!context) return children;
  const active = context.state.status === "ready" ? context.state.active : null;
  if (!active) return fallback;
  return (
    <QueryClientProvider key={active.cacheKey} cacheKey={active.cacheKey}>
      {children}
    </QueryClientProvider>
  );
}
