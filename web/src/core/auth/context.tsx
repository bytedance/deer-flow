// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

"use client";

import { createContext, useContext, useEffect, useState } from "react";
import type { ReactNode } from "react";

import { resolveServiceURL } from "~/core/api/resolve-service-url";

import {
  clearAuthData,
  getAuthHeaders,
  getAuthToken,
  getUserData,
  storeAuthData,
  type User,
} from "./utils";

// Define auth context type
interface AuthContextType {
  user: User | null;
  login: (email: string, password: string) => Promise<boolean>;
  logout: () => Promise<void>;
  isLoading: boolean;
}

// Create context
const AuthContext = createContext<AuthContextType | undefined>(undefined);

// Auth provider component
export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  // Check if user is already logged in on app start with token validation
  useEffect(() => {
    const checkAuth = async () => {
      try {
        const token = getAuthToken();
        if (token) {
          // Validate token expiration
          const response = await fetch(resolveServiceURL("auth/validate"), {
            method: "POST",
            headers: getAuthHeaders(),
          });

          if (response.ok) {
            const userData = getUserData();
            if (userData?.id && userData.email) {
              setUser(userData);
            }
          } else {
            // Token is invalid or expired, clear auth data
            clearAuthData();
          }
        }
      } catch (error) {
        console.error("Auth check error:", error);
        clearAuthData();
      } finally {
        setIsLoading(false);
      }
    };

    void checkAuth();
    void checkAuth();
  }, []);

  const login = async (email: string, password: string): Promise<boolean> => {
    try {
      setIsLoading(true);
      
      // Call the backend login API
      const response = await fetch(resolveServiceURL("auth/login"), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ email, password }),
      });
      
      if (response.ok) {
        const data = await response.json();
        if (data?.access_token && data?.user) {
          storeAuthData(data.access_token, data.user);
          setUser(data.user);
        } else {
          throw new Error("Invalid login response");
        }
        return true;
      } else {
        const errorData = await response.json();
        throw new Error(errorData.detail ?? "Login failed");
      }
    } catch (error) {
      console.error("Login error:", error);
      return false;
    } finally {
      setIsLoading(false);
    }
  };

  const logout = async () => {
    try {
      const token = getAuthToken();
      if (token) {
        // Call the backend logout API
        await fetch(resolveServiceURL("auth/logout"), {
          method: "POST",
          headers: getAuthHeaders(),
        });
      }
    } catch (error) {
      console.error("Logout error:", error);
    } finally {
      // Clear auth data using centralized utility
      clearAuthData();
      setUser(null);
    }
  };

  return (
    <AuthContext.Provider value={{ user, login, logout, isLoading }}>
      {children}
    </AuthContext.Provider>
  );
}

// Custom hook to use auth context
export function useAuth() {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}

// Helper hooks for specific checks
export function useIsAdmin() {
  const { user } = useAuth();
  return user?.role === "admin";
}

export function useIsAuthenticated() {
  const { user } = useAuth();
  return !!user;
}