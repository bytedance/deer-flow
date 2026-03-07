import { useQueryClient } from "@tanstack/react-query";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

import { resetAPIClient } from "@/core/api";
import { reloadLocalSettingsSnapshot } from "@/core/settings";
import { env } from "@/env";

import {
  fetchCurrentUser,
  loginUser,
  logoutUser,
  refreshToken,
  registerUser,
} from "./api";
import { clearAccessToken, getAccessToken, isTokenExpired } from "./token";
import type { AuthState, UserResponse } from "./types";

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: React.PropsWithChildren) {
  const queryClient = useQueryClient();
  const [user, setUser] = useState<UserResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  // On mount, try to restore session from stored token
  useEffect(() => {
    // In Electron mode, skip auth entirely
    if (env.IS_ELECTRON) {
      setIsLoading(false);
      return;
    }

    const init = async () => {
      const token = getAccessToken();
      if (!token) {
        reloadLocalSettingsSnapshot();
        setIsLoading(false);
        return;
      }

      // If token is expired, try refresh
      if (isTokenExpired(token, 0)) {
        const newToken = await refreshToken();
        if (!newToken) {
          clearAccessToken();
          reloadLocalSettingsSnapshot();
          setIsLoading(false);
          return;
        }
      }

      // Fetch user profile
      const profile = await fetchCurrentUser();
      if (profile) {
        setUser(profile);
      } else {
        clearAccessToken();
      }
      reloadLocalSettingsSnapshot();
      setIsLoading(false);
    };

    void init();
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const response = await loginUser(email, password);
    setUser(response.user);
    reloadLocalSettingsSnapshot();
  }, []);

  const register = useCallback(
    async (email: string, password: string, displayName?: string) => {
      const response = await registerUser(email, password, displayName);
      setUser(response.user);
      reloadLocalSettingsSnapshot();
    },
    [],
  );

  const logout = useCallback(async () => {
    await logoutUser();
    setUser(null);
    queryClient.clear();
    resetAPIClient();
    reloadLocalSettingsSnapshot();
  }, [queryClient]);

  const value = useMemo<AuthState>(
    () => ({
      user,
      isAuthenticated: user !== null,
      isLoading,
      login,
      register,
      logout,
    }),
    [user, isLoading, login, register, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}
