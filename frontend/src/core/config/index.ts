import { env } from "@/env";

export function getBackendBaseURL() {
  if (env.NEXT_PUBLIC_BACKEND_BASE_URL) {
    if (typeof window !== "undefined") {
      return new URL(env.NEXT_PUBLIC_BACKEND_BASE_URL, window.location.origin).toString();
    }
    return env.NEXT_PUBLIC_BACKEND_BASE_URL;
  }
  return "";
}

export function getLangGraphBaseURL(isMock?: boolean) {
  if (env.NEXT_PUBLIC_LANGGRAPH_BASE_URL) {
    if (typeof window !== "undefined") {
      return new URL(env.NEXT_PUBLIC_LANGGRAPH_BASE_URL, window.location.origin).toString();
    }
    return env.NEXT_PUBLIC_LANGGRAPH_BASE_URL;
  } else if (isMock) {
    if (typeof window !== "undefined") {
      return `${window.location.origin}/mock/api`;
    }
    return "http://localhost:3000/mock/api";
  } else {
    if (typeof window !== "undefined") {
      return `${window.location.origin}/api/langgraph`;
    }
    return "http://localhost:2026/api/langgraph";
  }
}
