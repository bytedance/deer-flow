// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { cookies } from 'next/headers';
// import { jwtVerify } from 'jose'; // Commented out as it's not currently used

// Define user types
export type UserRole = "admin" | "user";

export interface User {
  id: string;
  email: string;
  name: string;
  role: UserRole;
  exp: number;
  sub: string;
}

// Get user from cookies on server side
export async function getUserFromCookies(): Promise<User | null> {
  try {
    const cookieStore = await cookies();
    const token = cookieStore.get('authToken')?.value;
    
    if (!token) {
      return null;
    }
    
    // In a real implementation, you would verify the JWT token with your secret
    // For now, we'll parse the token to extract user info
    const tokenParts = token.split('.');
    if (tokenParts.length !== 3 || !tokenParts[1]) {
      return null;
    }
    
    const payload = JSON.parse(atob(tokenParts[1]));
    
    // Check if token is expired
    if (payload.exp && payload.exp < Date.now() / 1000) {
      return null;
    }
    
    return {
      id: payload.sub,
      email: payload.email,
      name: payload.email?.split('@')[0] ?? '',
      role: payload.role ?? 'user',
      exp: payload.exp,
      sub: payload.sub
    };
  } catch (error) {
    console.error('Error getting user from cookies:', error);
    return null;
  }
}

// Check if user is admin
export async function isAdminUser(): Promise<boolean> {
  const user = await getUserFromCookies();
  return user?.role === 'admin' || false;
}

// Check if user is authenticated
export async function isAuthenticated(): Promise<boolean> {
  const user = await getUserFromCookies();
  return !!user;
}