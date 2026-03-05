import { env } from "@/env";

export function getBackendBaseURL() {
  const base = env.VITE_BACKEND_BASE_URL?.trim();
  if (!base) {
    return "";
  }
  const normalized = base.replace(/\/+$/, "");
  if (normalized.endsWith("/api")) {
    return normalized.slice(0, -4);
  }
  return normalized;
}

export function getLangGraphBaseURL() {
  if (env.VITE_LANGGRAPH_BASE_URL) {
    return env.VITE_LANGGRAPH_BASE_URL;
  }
  // LangGraph SDK requires a full URL, construct it from current origin
  if (typeof window !== "undefined") {
    return `${window.location.origin}/api/langgraph`;
  }
  // Fallback for Electron
  return "http://localhost:2024";
}

export { loadAppConfig } from "./api";
export { DEFAULT_APP_CONFIG, useAppConfig } from "./hooks";
