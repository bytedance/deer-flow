import { getAuthHeaders } from "~/core/auth/utils";

import { resolveServiceURL } from "./resolve-service-url";

export interface User {
  id: string;
  email: string;
  name: string;
  role: "admin" | "user";
}

export interface CreateUserRequest {
  email: string;
  password: string;
  name: string;
  role: "admin" | "user";
}

export interface UpdateUserRequest {
  name?: string;
  role?: "admin" | "user";
}

export interface ChangePasswordRequest {
  old_password: string;
  new_password: string;
}

/**
 * Fetch all users (admin only)
 */
export async function fetchUsers(): Promise<User[]> {
  const response = await fetch(resolveServiceURL("admin/users"), {
    method: "GET",
    headers: getAuthHeaders(),
    cache: "no-store",
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Failed to fetch users" }));
    throw new Error(error.detail ?? "Failed to fetch users");
  }

  return response.json();
}

/**
 * Create a new user (admin only)
 */
export async function createUser(data: CreateUserRequest): Promise<User> {
  const response = await fetch(resolveServiceURL("admin/users"), {
    method: "POST",
    headers: getAuthHeaders(),
    body: JSON.stringify(data),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Failed to create user" }));
    throw new Error(error.detail ?? "Failed to create user");
  }

  return response.json();
}

/**
 * Update a user's name and/or role (admin only)
 */
export async function updateUser(userId: string, data: UpdateUserRequest): Promise<User> {
  const response = await fetch(resolveServiceURL(`admin/users/${userId}`), {
    method: "PUT",
    headers: getAuthHeaders(),
    body: JSON.stringify(data),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Failed to update user" }));
    throw new Error(error.detail ?? "Failed to update user");
  }

  return response.json();
}

/**
 * Delete a user (admin only)
 */
export async function deleteUser(userId: string): Promise<void> {
  const response = await fetch(resolveServiceURL(`admin/users/${userId}`), {
    method: "DELETE",
    headers: getAuthHeaders(),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Failed to delete user" }));
    throw new Error(error.detail ?? "Failed to delete user");
  }
}

/**
 * Change current user's password
 */
export async function changePassword(oldPassword: string, newPassword: string): Promise<void> {
  const response = await fetch(resolveServiceURL("auth/password"), {
    method: "PUT",
    headers: getAuthHeaders(),
    body: JSON.stringify({
      old_password: oldPassword,
      new_password: newPassword,
    }),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Failed to change password" }));
    throw new Error(error.detail ?? "Failed to change password");
  }
}
