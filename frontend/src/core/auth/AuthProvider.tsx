"use client";

import { useRouter, usePathname } from "next/navigation";
import React, {
  createContext,
  useContext,
  useState,
  useCallback,
  useEffect,
  type ReactNode,
} from "react";

import { useArtifactDraftOwner } from "@/core/artifacts/draft-context";

import { isStaticWebsiteOnly } from "../static-mode";

import { AuthQueryScopeContext } from "./query-scope";
import {
  ACCOUNT_DISABLED_LOGIN_URL,
  type User,
  buildLoginUrl,
  currentReturnPath,
  parseAuthError,
} from "./types";

// Re-export for consumers
export type { User };

/**
 * Authentication context provided to consuming components
 */
interface AuthContextType {
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  logout: () => Promise<void>;
  refreshUser: () => Promise<void>;
  applyUser: (user: User | null) => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

/**
 * True when the SSR auth verdict for this auth-page render was
 * `account_disabled`: the visitor holds a live session cookie for a
 * suspended account, so /login states the known reason immediately instead
 * of waiting for a login attempt the backend deliberately answers with the
 * generic invalid-credentials message (#4063 gap 3).
 */
export const AuthDisabledContext = createContext(false);

interface AuthProviderProps {
  children: ReactNode;
  initialUser: User | null;
  /** The Gateway could not determine authentication; null is not a confirmed logout. */
  initialAuthUnknown?: boolean;
}

/**
 * AuthProvider - Unified authentication context for the application
 *
 * Per RFC-001:
 * - Only holds display information (user), never JWT or tokens
 * - initialUser comes from server-side guard, avoiding client flicker
 * - Provides logout and refresh capabilities
 */
export function AuthProvider({
  children,
  initialUser,
  initialAuthUnknown = false,
}: AuthProviderProps) {
  const [user, setUser] = useState<User | null>(initialUser);
  const [authKnown, setAuthKnown] = useState(!initialAuthUnknown);
  const authQueryScope = authKnown ? (user?.id ?? null) : undefined;
  useArtifactDraftOwner(authQueryScope);
  const [isLoading, setIsLoading] = useState(false);
  // Logout and externally confirmed users supersede pending auth refreshes.
  const authRequestRef = React.useRef(0);
  const authRefreshInFlightRef = React.useRef(false);
  const reconnectPendingRef = React.useRef(false);
  const router = useRouter();
  const pathname = usePathname();
  const staticMode = isStaticWebsiteOnly();

  const isAuthenticated = user !== null;

  /**
   * Apply a user value supplied by a caller (e.g. banner probe) that has
   * already fetched it. Equivalent to setUser, exposed with a stable name
   * so consumers don't reach into React internals.
   */
  const applyUser = useCallback((next: User | null) => {
    authRequestRef.current++;
    authRefreshInFlightRef.current = false;
    reconnectPendingRef.current = false;
    setUser(next);
    setAuthKnown(true);
    setIsLoading(false);
  }, []);

  /**
   * Fetch current user from FastAPI
   * Used when initialUser might be stale (e.g., after tab was inactive)
   */
  const refreshUser = useCallback(async () => {
    if (staticMode) return;
    const requestId = ++authRequestRef.current;
    authRefreshInFlightRef.current = true;

    try {
      setIsLoading(true);
      const res = await fetch("/api/v1/auth/me", {
        credentials: "include",
      });
      if (requestId !== authRequestRef.current) return;

      if (res.ok) {
        const data = await res.json();
        if (requestId !== authRequestRef.current) return;
        setUser(data);
        setAuthKnown(true);
      } else if (res.status === 401) {
        setUser(null);
        setAuthKnown(true);
        const code = await res
          .json()
          .then((data) => parseAuthError(data).code)
          .catch(() => null);
        if (requestId !== authRequestRef.current) return;
        if (code === "account_disabled") {
          // Operator-disabled account (#4063 gap 3): the login page states
          // the reason. Unlike an expired session there is nothing to come
          // back to, so no `next` is preserved and the path gate does not
          // apply — every authenticated page is equally unreachable.
          router.push(ACCOUNT_DISABLED_LOGIN_URL);
        } else if (pathname?.startsWith("/workspace")) {
          // Session expired or invalid — redirect on protected routes
          router.push(buildLoginUrl(currentReturnPath()));
        }
      }
    } catch (err) {
      if (requestId !== authRequestRef.current) return;
      console.error("Failed to refresh user:", err);
      setUser(null);
      setAuthKnown(false);
    } finally {
      if (requestId === authRequestRef.current) {
        authRefreshInFlightRef.current = false;
        setIsLoading(false);
      }
    }
  }, [staticMode, pathname, router]);

  /**
   * Logout - call FastAPI logout endpoint and clear local state
   * Per RFC-001: Immediately clear local state, don't wait for server confirmation
   *
   * When the gateway is unreachable the fetch silently fails — the SPA
   * router.push("/") would leave the user on "/" still holding stale
   * React state and any in-flight SSE / fetch / query subscriptions.
   * We therefore fall back to a hard navigation (window.location.href),
   * which discards all client state the same way the legacy form-POST
   * logout used to.
   */
  const logout = useCallback(async () => {
    // Immediately clear local state to prevent UI flicker
    authRequestRef.current++;
    authRefreshInFlightRef.current = false;
    reconnectPendingRef.current = false;
    setUser(null);
    setAuthKnown(true);
    setIsLoading(false);

    if (staticMode) {
      router.push("/");
      return;
    }

    let logoutFailed = false;
    try {
      const res = await fetch("/api/v1/auth/logout", {
        method: "POST",
        credentials: "include",
      });
      if (!res.ok) logoutFailed = true;
    } catch (err) {
      console.error("Logout request failed:", err);
      logoutFailed = true;
    }

    if (logoutFailed && typeof window !== "undefined") {
      // Hard navigation ensures every in-flight subscription is torn down,
      // matching the legacy form-POST logout behaviour during a gateway outage.
      window.location.href = "/";
      return;
    }

    // Redirect to home page
    router.push("/");
  }, [staticMode, router]);

  /**
   * Revalidate visible tabs, including unknown auth after a transport failure.
   * Tab switches are throttled to 60 s; reconnect wakes unknown auth immediately.
   */
  const lastCheckRef = React.useRef(0);

  useEffect(
    () => () => {
      reconnectPendingRef.current = false;
    },
    [],
  );

  useEffect(() => {
    if (staticMode) return;

    const checkUser = (reconnecting = false) => {
      if (user === null && authKnown) return;
      if (reconnecting) reconnectPendingRef.current = true;
      if (
        document.visibilityState !== "visible" ||
        authRefreshInFlightRef.current
      )
        return;
      const now = Date.now();
      if (!reconnectPendingRef.current && now - lastCheckRef.current < 60_000)
        return;
      reconnectPendingRef.current = false;
      lastCheckRef.current = now;
      void refreshUser();
    };
    const handleVisibilityChange = () => checkUser();
    const handleOnline = () => {
      if (!authKnown || authRefreshInFlightRef.current) checkUser(true);
    };

    // isLoading re-runs this effect when a failed request leaves auth unchanged.
    if (reconnectPendingRef.current && !authRefreshInFlightRef.current) {
      if (authKnown) reconnectPendingRef.current = false;
      else checkUser();
    }

    document.addEventListener("visibilitychange", handleVisibilityChange);
    window.addEventListener("online", handleOnline);
    return () => {
      document.removeEventListener("visibilitychange", handleVisibilityChange);
      window.removeEventListener("online", handleOnline);
    };
  }, [staticMode, user, authKnown, isLoading, refreshUser]);

  const value: AuthContextType = {
    user,
    isAuthenticated,
    isLoading,
    logout,
    refreshUser,
    applyUser,
  };

  return (
    <AuthContext.Provider value={value}>
      <AuthQueryScopeContext.Provider value={authQueryScope}>
        {children}
      </AuthQueryScopeContext.Provider>
    </AuthContext.Provider>
  );
}

/**
 * Hook to access authentication context
 * Throws if used outside AuthProvider - this is intentional for proper usage
 */
export function useAuth(): AuthContextType {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}

/**
 * Hook to require authentication - redirects to login if not authenticated
 * Useful for client-side checks in addition to server-side guards
 */
export function useRequireAuth(): AuthContextType {
  const auth = useAuth();
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    if (isStaticWebsiteOnly()) return;

    // Only redirect if we're sure user is not authenticated (not just loading)
    if (!auth.isLoading && !auth.isAuthenticated) {
      router.push(buildLoginUrl(currentReturnPath()));
    }
  }, [auth.isAuthenticated, auth.isLoading, router, pathname]);

  return auth;
}
