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

import { isStaticWebsiteOnly } from "../static-mode";

import { type User, buildLoginUrl } from "./types";

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
  /**
   * Register/clear a deferral of the automatic 401 login redirect. The PAT
   * show-once flow uses it: a session expiring while the raw token is
   * displayed must not navigate the workspace away and discard the
   * credential's only copy — the pending redirect fires as soon as the
   * last deferral clears (see {@link useDeferLoginRedirect}).
   */
  setLoginRedirectDeferral: (active: boolean) => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

interface AuthProviderProps {
  children: ReactNode;
  initialUser: User | null;
}

/**
 * AuthProvider - Unified authentication context for the application
 *
 * Per RFC-001:
 * - Only holds display information (user), never JWT or tokens
 * - initialUser comes from server-side guard, avoiding client flicker
 * - Provides logout and refresh capabilities
 */
export function AuthProvider({ children, initialUser }: AuthProviderProps) {
  const [user, setUser] = useState<User | null>(initialUser);
  const [isLoading, setIsLoading] = useState(false);
  const [loginRedirectDeferrals, setLoginRedirectDeferrals] = useState(0);
  const [pendingLoginRedirect, setPendingLoginRedirect] = useState<string | null>(null);
  const router = useRouter();
  const pathname = usePathname();
  const staticMode = isStaticWebsiteOnly();

  const isAuthenticated = user !== null;

  const setLoginRedirectDeferral = useCallback((active: boolean) => {
    setLoginRedirectDeferrals((count) => (active ? count + 1 : Math.max(0, count - 1)));
  }, []);

  /**
   * Apply a user value supplied by a caller (e.g. banner probe) that has
   * already fetched it. Equivalent to setUser, exposed with a stable name
   * so consumers don't reach into React internals.
   */
  const applyUser = useCallback((next: User | null) => {
    setUser(next);
  }, []);

  /**
   * Fetch current user from FastAPI
   * Used when initialUser might be stale (e.g., after tab was inactive)
   */
  const refreshUser = useCallback(async () => {
    if (staticMode) return;

    try {
      setIsLoading(true);
      const res = await fetch("/api/v1/auth/me", {
        credentials: "include",
      });

      if (res.ok) {
        const data = await res.json();
        setUser(data);
      } else if (res.status === 401) {
        // Session expired or invalid
        setUser(null);
        // Redirect to login if on a protected route. A deferral holds the
        // redirect: the soft navigation would unmount the deferring flow
        // (the PAT show-once dialog) without firing beforeunload and
        // discard the only copy of an active credential — session expiry
        // does not revoke a minted token.
        if (pathname?.startsWith("/workspace")) {
          const target = buildLoginUrl(pathname);
          if (loginRedirectDeferrals > 0) {
            setPendingLoginRedirect(target);
          } else {
            router.push(target);
          }
        }
      }
    } catch (err) {
      console.error("Failed to refresh user:", err);
      setUser(null);
    } finally {
      setIsLoading(false);
    }
  }, [staticMode, pathname, router, loginRedirectDeferrals]);

  // The held redirect fires the moment the last deferral clears.
  useEffect(() => {
    if (pendingLoginRedirect === null || loginRedirectDeferrals > 0) return;
    router.push(pendingLoginRedirect);
    setPendingLoginRedirect(null);
  }, [pendingLoginRedirect, loginRedirectDeferrals, router]);

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
    setUser(null);

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
   * Handle visibility change - refresh user when tab becomes visible again.
   * Throttled to at most once per 60 s to avoid spamming the backend on rapid tab switches.
   */
  const lastCheckRef = React.useRef(0);

  useEffect(() => {
    if (staticMode) return;

    const handleVisibilityChange = () => {
      if (document.visibilityState !== "visible" || user === null) return;
      const now = Date.now();
      if (now - lastCheckRef.current < 60_000) return;
      lastCheckRef.current = now;
      void refreshUser();
    };

    document.addEventListener("visibilitychange", handleVisibilityChange);
    return () => {
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [staticMode, user, refreshUser]);

  const value: AuthContextType = {
    user,
    isAuthenticated,
    isLoading,
    logout,
    refreshUser,
    applyUser,
    setLoginRedirectDeferral,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

/**
 * Defer the provider's automatic 401 login redirect while *active* is true.
 * Deferrals are counted — multiple deferrers never cancel each other — and
 * the held redirect fires as soon as the last one clears. Used by flows
 * whose one-time output cannot survive an unmount: the PAT show-once token
 * stays active after a session expires (expiry does not revoke it), so
 * navigating its page away would permanently discard the credential's only
 * raw copy.
 *
 * Also returns an imperative ``arm()`` channel: it registers a deferral
 * synchronously and hands back its release. The *active* channel rides a
 * render+effect, which is one commit late — callers who must be protected
 * inside the synchronous submission window (a pending /me refresh can
 * answer 401 before the pending state has rendered) arm it in the same
 * breath they start the request, then release once the *active* channel
 * has taken over.
 */
export function useDeferLoginRedirect(active: boolean): () => () => void {
  const { setLoginRedirectDeferral } = useAuth();
  useEffect(() => {
    if (!active) return;
    setLoginRedirectDeferral(true);
    return () => setLoginRedirectDeferral(false);
  }, [active, setLoginRedirectDeferral]);
  const arm = useCallback(() => {
    setLoginRedirectDeferral(true);
    return () => setLoginRedirectDeferral(false);
  }, [setLoginRedirectDeferral]);
  return arm;
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
      router.push(buildLoginUrl(pathname || "/workspace"));
    }
  }, [auth.isAuthenticated, auth.isLoading, router, pathname]);

  return auth;
}
