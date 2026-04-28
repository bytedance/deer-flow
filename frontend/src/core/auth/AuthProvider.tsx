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

  /**
   * Fetch current user from FastAPI
   * Used when initialUser might be stale (e.g., after tab was inactive)
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
      setUser(null);
    } finally {
      setIsLoading(false);
    }
  }, [pathname, router]);

  /**
   * Logout - call FastAPI logout endpoint and clear local state
   * Per RFC-001: Immediately clear local state, don't wait for server confirmation
   */
  const logout = useCallback(async () => {
    // Immediately clear local state to prevent UI flicker
    setUser(null);

    try {
      await fetch("/api/v1/auth/logout", {
        method: "POST",
        credentials: "include",
      });
    } catch (err) {
      console.error("Logout request failed:", err);
      // Still redirect even if logout request fails
    }

    // Redirect to home page
    router.push("/");
  }, [router]);

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
