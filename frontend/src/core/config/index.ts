import { env } from "@/env";

import { getServerBackendBaseURL } from "./server-backend-base-url";
import { getServerBaseOrigin } from "./server-base-origin";

function getBaseOrigin() {
  if (typeof window !== "undefined") {
    return window.location.origin;
  }
  return getServerBaseOrigin();
}

export function getBackendBaseURL() {
  if (typeof window === "undefined") {
    return getServerBackendBaseURL();
  }

  if (env.NEXT_PUBLIC_BACKEND_BASE_URL) {
    return new URL(env.NEXT_PUBLIC_BACKEND_BASE_URL, getBaseOrigin())
      .toString()
      .replace(/\/+$/, "");
  } else {
    return "";
  }
}

export function getLangGraphBaseURL(isMock?: boolean) {
  if (env.NEXT_PUBLIC_LANGGRAPH_BASE_URL) {
    return new URL(
      env.NEXT_PUBLIC_LANGGRAPH_BASE_URL,
      getBaseOrigin(),
    ).toString();
  } else if (isMock) {
    if (typeof window !== "undefined") {
      return `${window.location.origin}/mock/api`;
    }
    return "http://localhost:3000/mock/api";
  } else {
    // LangGraph SDK requires a full URL, construct it from current origin
    if (typeof window !== "undefined") {
      return `${window.location.origin}/api/langgraph`;
    }
    // Fallback for SSR
    return "http://localhost:2026/api/langgraph";
  }
}
