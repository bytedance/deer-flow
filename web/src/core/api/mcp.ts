// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import type { SimpleMCPServerMetadata } from "../mcp";

import { resolveServiceURL } from "./resolve-service-url";

// Get auth token from localStorage
function getAuthToken() {
  if (typeof window !== "undefined") {
    return localStorage.getItem("authToken");
  }
  return null;
}

export async function queryMCPServerMetadata(config: SimpleMCPServerMetadata, signal?: AbortSignal) {
  const token = getAuthToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  
  const response = await fetch(resolveServiceURL("mcp/server/metadata"), {
    method: "POST",
    headers,
    body: JSON.stringify(config),
    signal,
  });
  if (!response.ok) {
    throw new Error(`HTTP error! status: ${response.status}`);
  }
  return response.json();
}
