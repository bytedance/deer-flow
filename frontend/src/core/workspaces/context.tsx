"use client";

import {
  createContext,
  useContext,
  useCallback,
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
  /** A navigation locator, never an authorization grant. */
  readonly requestedWorkspaceId?: string;
  readonly signInHref?: string;
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
  initialWorkspaceId,
  children,
}: {
  actorUserId: string;
  initialWorkspaceId?: string;
  children: ReactNode;
}) {
  const [session] = useState(
    () => new WorkspaceSession(actorUserId, initialWorkspaceId),
  );
  const state = useSyncExternalStore(
    session.subscribe,
    session.getSnapshot,
    session.getServerSnapshot,
  );
  useEffect(() => session.acquire(), [session]);
  const value = useMemo(
    () => ({
      state,
      requestedWorkspaceId: session.getRequestedSelector(),
      select: session.select,
      refresh: session.refresh,
    }),
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
  initialWorkspaceId,
  children,
}: {
  enabled?: boolean;
  initialWorkspaceId?: string;
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
    <ActorWorkspaceProvider
      key={JSON.stringify([actorUserId, initialWorkspaceId ?? null])}
      actorUserId={actorUserId}
      initialWorkspaceId={initialWorkspaceId}
    >
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

/** Shell regions share their parent's lifetime cache; this gate only mounts content. */
export function WorkspaceContentBoundary({
  children,
  fallback = null,
}: {
  children: ReactNode;
  fallback?: ReactNode;
}) {
  const context = useWorkspaceContext();
  if (context && (context.state.status !== "ready" || !context.state.active))
    return fallback;
  return children;
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

/** Match the confirmed authority to the URL before mounting any private route. */
export function WorkspaceRouteBoundary({
  selector,
  onSelect,
  onPersonalConfirmed,
  signInHref,
  children,
}: {
  selector?: string;
  onSelect: (selector?: string) => void;
  onPersonalConfirmed: (workspaceId: string) => void;
  signInHref: string;
  children: ReactNode;
}) {
  const context = useWorkspaceContext();
  const active = context?.state.active;
  useEffect(() => {
    if (
      selector === undefined &&
      context?.requestedWorkspaceId === undefined &&
      active &&
      !active.scope.signal.aborted
    )
      onPersonalConfirmed(active.scope.workspaceId);
  }, [selector, context?.requestedWorkspaceId, active, onPersonalConfirmed]);
  const select = useCallback(
    (id?: string) => {
      if (!context || context.state.active?.scope.signal.aborted)
        return Promise.resolve(false);
      // Detach old private content synchronously; routing cannot retarget its lifetime.
      const result = context.select(id);
      onSelect(id);
      return result;
    },
    [context, onSelect],
  );
  const value = useMemo(() => {
    if (!context) return null;
    const state =
      context.state.status === "ready" && active?.scope.workspaceId !== selector
        ? Object.freeze({
            ...context.state,
            status: "loading" as const,
            active: null,
          })
        : context.state;
    return { ...context, state, select, signInHref };
  }, [context, active, selector, select, signInHref]);
  return (
    <WorkspaceContext.Provider value={value}>
      {children}
    </WorkspaceContext.Provider>
  );
}
