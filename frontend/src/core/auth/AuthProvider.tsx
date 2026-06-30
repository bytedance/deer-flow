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

import { queryClient } from "@/components/query-client-provider";
import { useBlockStore } from "@/core/genui/store";
import { useChartScreenshotStore } from "@/core/genui/chart-screenshots";
import { setCurrentTenantId } from "@/core/tenant/store";
import {
  EHM_AUTH_SUCCESS_EVENT,
  EHM_LOGOUT_EVENT,
} from "@/core/auth/ehm-host-bridge";

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
  logout: (options?: { skipNavigation?: boolean }) => Promise<void>;
  refreshUser: () => Promise<void>;
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
  const router = useRouter();
  const pathname = usePathname();

  const isAuthenticated = user !== null;

  // Sync tenant store when initialUser is available on mount
  useEffect(() => {
    if (initialUser?.tenant_id) {
      setCurrentTenantId(initialUser.tenant_id);
    }
  }, [initialUser]);

  /**
   * Fetch current user from FastAPI
   * Used when initialUser might be stale (e.g., after tab was inactive).
   */
  const refreshUser = useCallback(async () => {
    try {
      setIsLoading(true);
      const res = await fetch("/api/v1/auth/me", {
        credentials: "include",
      });

      if (res.ok) {
        const data = await res.json();
        setUser(data);
        if (data.tenant_id) {
          setCurrentTenantId(data.tenant_id);
        }
      } else if (res.status === 401) {
        // Session expired or invalid
        setUser(null);
        // Redirect to login if on a protected route
        if (pathname?.startsWith("/workspace")) {
          router.push(buildLoginUrl(pathname));
        }
      }
    } catch (err) {
      console.error("Failed to refresh user:", err);
      // Keep the last known user on transient network errors; only a confirmed
      // 401 should clear the session UI state.
    } finally {
      setIsLoading(false);
    }
  }, [pathname, router]);

  /**
   * Logout - call FastAPI logout endpoint
   * Per RFC-001: Immediately clear local state, don't wait for server confirmation
   *
   * Note: When triggered by EHM host (AI_LOGOUT), we don't navigate — EHM controls the flow.
   * When triggered by user clicking logout button, we navigate to home.
   */
  const logout = useCallback(
    async (options?: { skipNavigation?: boolean }) => {
      // Clear authentication state
      setUser(null);
      queryClient.clear();

      // Clear all frontend state stores to prevent UI leakage between accounts
      useBlockStore.getState().reset();
      useChartScreenshotStore.getState().clearAll();

      try {
        await fetch("/api/v1/auth/logout", {
          method: "POST",
          credentials: "include",
        });
      } catch (err) {
        console.error("Logout request failed:", err);
      }

      // Only navigate if not triggered by EHM host
      if (!options?.skipNavigation) {
        router.push("/");
      }
    },
    [router],
  );

  /**
   * Handle visibility change - refresh user when tab becomes visible again.
   * Throttled to at most once per 60 s to avoid spamming the backend on rapid tab switches.
   */
  const lastCheckRef = React.useRef(0);

  useEffect(() => {
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
  }, [user, refreshUser]);

  /**
   * Handle EHM host logout — when embedded in EHM iframe and EHM logs out,
   * EHM sends an AI_LOGOUT postMessage to the iframe. The host bridge
   * dispatches this custom event so we can sync the logout.
   *
   * We pass skipNavigation: true because EHM controls the navigation flow
   * (it will send AI_INIT with the new account's token after logout).
   */
  useEffect(() => {
    const handleEhmLogout = () => {
      console.info("[AuthProvider] EHM logout received, clearing session");
      void logout({ skipNavigation: true });
    };
    window.addEventListener(EHM_LOGOUT_EVENT, handleEhmLogout);
    return () => {
      window.removeEventListener(EHM_LOGOUT_EVENT, handleEhmLogout);
    };
  }, [logout]);

  /**
   * Handle EHM auth success — after reauthenticateWithEhmToken succeeds,
   * refresh the user state so the UI shows the new account.
   */
  useEffect(() => {
    const handleEhmAuthSuccess = () => {
      console.info("[AuthProvider] EHM auth success, refreshing user");
      void refreshUser();
    };
    window.addEventListener(EHM_AUTH_SUCCESS_EVENT, handleEhmAuthSuccess);
    return () => {
      window.removeEventListener(EHM_AUTH_SUCCESS_EVENT, handleEhmAuthSuccess);
    };
  }, [refreshUser]);

  const value: AuthContextType = {
    user,
    isAuthenticated,
    isLoading,
    logout,
    refreshUser,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
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
    // Only redirect if we're sure user is not authenticated (not just loading)
    if (!auth.isLoading && !auth.isAuthenticated) {
      router.push(buildLoginUrl(pathname || "/workspace"));
    }
  }, [auth.isAuthenticated, auth.isLoading, router, pathname]);

  return auth;
}
