// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

/**
 * Centralized authentication utilities for token management and security
 */

// JWT token interface
export interface JWTPayload {
  sub: string;
  email: string;
  role: "admin" | "user";
  exp: number;
  iat?: number;
}

// User interface
export interface User {
  id: string;
  email: string;
  name: string;
  role: "admin" | "user";
}

// Auth configuration
const AUTH_CONFIG = {
  TOKEN_KEY: "authToken",
  USER_DATA_KEY: "userData",
  CSRF_TOKEN_KEY: "csrfToken",
  TOKEN_HEADER: "Authorization",
  TOKEN_PREFIX: "Bearer ",
  DEFAULT_TTL: 24 * 60 * 60 * 1000, // 24 hours in milliseconds
} as const;

/**
 * Get stored authentication token from localStorage
 */
export function getAuthToken(): string | null {
  if (typeof window === "undefined") return null;
  
  try {
    return localStorage.getItem(AUTH_CONFIG.TOKEN_KEY);
  } catch (error) {
    console.error("Error accessing localStorage:", error);
    return null;
  }
}

/**
 * Get stored CSRF token from localStorage
 */
export function getCSRFToken(): string | null {
  if (typeof window === "undefined") return null;
  
  try {
    return localStorage.getItem(AUTH_CONFIG.CSRF_TOKEN_KEY);
  } catch (error) {
    console.error("Error accessing localStorage:", error);
    return null;
  }
}

/**
 * Store authentication token and user data
 */
export function storeAuthData(token: string, user: User): void {
  if (typeof window === "undefined") return;
  
  try {
    localStorage.setItem(AUTH_CONFIG.TOKEN_KEY, token);
    localStorage.setItem(AUTH_CONFIG.USER_DATA_KEY, JSON.stringify(user));
    
    // Store token in cookie for server-side access
    document.cookie = `${AUTH_CONFIG.TOKEN_KEY}=${token}; path=/; max-age=${AUTH_CONFIG.DEFAULT_TTL / 1000}; SameSite=Lax; Secure`;
  } catch (error) {
    console.error("Error storing auth data:", error);
  }
}

/**
 * Clear all authentication data
 */
export function clearAuthData(): void {
  if (typeof window === "undefined") return;
  
  try {
    localStorage.removeItem(AUTH_CONFIG.TOKEN_KEY);
    localStorage.removeItem(AUTH_CONFIG.USER_DATA_KEY);
    localStorage.removeItem(AUTH_CONFIG.CSRF_TOKEN_KEY);
    
    // Clear cookies
    document.cookie = `${AUTH_CONFIG.TOKEN_KEY}=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT`;
    document.cookie = `${AUTH_CONFIG.CSRF_TOKEN_KEY}=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT`;
  } catch (error) {
    console.error("Error clearing auth data:", error);
  }
}

/**
 * Parse and validate JWT token (client-side validation only)
 */
export function parseToken(token: string): JWTPayload | null {
  try {
    // Split token into parts
    const parts = token.split('.');
    if (parts.length !== 3) {
      return null;
    }
    
    // Decode payload (base64url)
    const payload = JSON.parse(atob(parts[1].replace(/-/g, '+').replace(/_/g, '/')));
    
    // Check if token is expired
    if (payload.exp && payload.exp * 1000 < Date.now()) {
      return null;
    }
    
    return payload;
  } catch (error) {
    console.error("Error parsing token:", error);
    return null;
  }
}

/**
 * Check if current token is valid (not expired)
 */
export function isTokenValid(): boolean {
  const token = getAuthToken();
  if (!token) return false;
  
  const payload = parseToken(token);
  return payload !== null;
}

/**
 * Get user data from localStorage
 */
export function getUserData(): User | null {
  if (typeof window === "undefined") return null;
  
  try {
    const userData = localStorage.getItem(AUTH_CONFIG.USER_DATA_KEY);
    return userData ? JSON.parse(userData) : null;
  } catch (error) {
    console.error("Error parsing user data:", error);
    return null;
  }
}

/**
 * Build authenticated headers for API requests
 */
export function getAuthHeaders(additionalHeaders: Record<string, string> = {}): Record<string, string> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...additionalHeaders,
  };
  
  const token = getAuthToken();
  if (token) {
    headers[AUTH_CONFIG.TOKEN_HEADER] = `${AUTH_CONFIG.TOKEN_PREFIX}${token}`;
  }
  
  const csrfToken = getCSRFToken();
  if (csrfToken) {
    headers["X-CSRF-Token"] = csrfToken;
  }
  
  return headers;
}

/**
 * Generate CSRF token
 */
export function generateCSRFToken(): string {
  return Array.from(crypto.getRandomValues(new Uint8Array(32)))
    .map(b => b.toString(16).padStart(2, '0'))
    .join('');
}

/**
 * Store CSRF token
 */
export function storeCSRFToken(token: string): void {
  if (typeof window === "undefined") return;
  
  try {
    localStorage.setItem(AUTH_CONFIG.CSRF_TOKEN_KEY, token);
    document.cookie = `${AUTH_CONFIG.CSRF_TOKEN_KEY}=${token}; path=/; max-age=${AUTH_CONFIG.DEFAULT_TTL / 1000}; SameSite=Strict; Secure`;
  } catch (error) {
    console.error("Error storing CSRF token:", error);
  }
}

/**
 * Check if user has specific role
 */
export function hasRole(requiredRole: "admin" | "user"): boolean {
  const userData = getUserData();
  return userData?.role === requiredRole;
}

/**
 * Get time until token expiration (in milliseconds)
 */
export function getTokenExpirationTime(): number {
  const token = getAuthToken();
  if (!token) return 0;
  
  const payload = parseToken(token);
  if (!payload?.exp) return 0;
  
  return Math.max(0, payload.exp * 1000 - Date.now());
}

/**
 * Check if token is about to expire (within 5 minutes)
 */
export function isTokenExpiringSoon(thresholdMs: number = 5 * 60 * 1000): boolean {
  const timeLeft = getTokenExpirationTime();
  return timeLeft > 0 && timeLeft <= thresholdMs;
}