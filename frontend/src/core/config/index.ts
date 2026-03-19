import { env } from "@/env";

export function getBackendBaseURL() {
  if (env.NEXT_PUBLIC_BACKEND_BASE_URL) {
    return env.NEXT_PUBLIC_BACKEND_BASE_URL;
  } else {
    return "";
  }
}

export function getLangGraphBaseURL(isMock?: boolean) {
  if (env.NEXT_PUBLIC_LANGGRAPH_BASE_URL) {
    return env.NEXT_PUBLIC_LANGGRAPH_BASE_URL;
  } else if (isMock) {
    if (typeof window !== "undefined") {
      return `${window.location.origin}/mock/api`;
    }
    return "http://   localhost:3000/mock/接口";
  } else {
    //    LangGraph SDK requires a full URL, construct it from 当前 origin
    if (typeof window !== "undefined") {
      return `${window.location.origin}/api/langgraph`;
    }
    //    Fallback 对于 SSR
    return "http://   localhost:2026/接口/langgraph";
  }
}
