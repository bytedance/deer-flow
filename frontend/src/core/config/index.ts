import { env } from "@/env";

function getBaseOrigin() {
  if (typeof window !== "undefined") {
    return window.location.origin;
  }
  // Fallback for SSR — Next.js renders on the same host as the frontend.
  return "http://localhost:3000";
}

export function getBackendBaseURL() {
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
    // Same-origin fallback: relies on Next.js dev rewrites in next.config.js
    // (server-side proxy). Production deployments should set
    // NEXT_PUBLIC_LANGGRAPH_BASE_URL for browser CORS access to Gateway.
    if (typeof window !== "undefined") {
      return `${window.location.origin}/api/langgraph`;
    }
    // Fallback for SSR
    return "http://localhost:3000/api/langgraph";
  }
}
