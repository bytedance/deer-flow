// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { env } from "~/env";

function getBaseURL(): string {
  // If NEXT_PUBLIC_API_URL is explicitly configured, use it
  if (env.NEXT_PUBLIC_API_URL) {
    return env.NEXT_PUBLIC_API_URL;
  }

  // Runtime detection: use the same hostname as the current page with port 8000
  // This allows cross-machine access without rebuilding (Issue #777)
  if (typeof window !== "undefined") {
    const { protocol, hostname } = window.location;
    return `${protocol}//${hostname}:8000/api/`;
  }

  // Fallback for SSR or when window is not available
  return "http://localhost:8000/api/";
}

export function resolveServiceURL(path: string) {
  let BASE_URL = getBaseURL();
  if (!BASE_URL.endsWith("/")) {
    BASE_URL += "/";
  }
  return new URL(path, BASE_URL).toString();
}
