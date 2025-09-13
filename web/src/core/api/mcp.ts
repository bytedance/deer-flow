// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import type { SimpleMCPServerMetadata } from "../mcp";

import { resolveServiceURL } from "./resolve-service-url";

import { getAuthHeaders } from "~/core/auth/utils";

export async function queryMCPServerMetadata(config: SimpleMCPServerMetadata, signal?: AbortSignal) {
  const response = await fetch(resolveServiceURL("mcp/server/metadata"), {
    method: "POST",
    headers: getAuthHeaders(),
    body: JSON.stringify(config),
    signal,
  });
  if (!response.ok) {
    throw new Error(`HTTP error! status: ${response.status}`);
  }
  return response.json();
}
