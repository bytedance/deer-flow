import {
  DEFAULT_AUTH_NEXT_PATH,
  resolveAuthNextPath,
  validateAuthNextPath,
} from "./next-path";
import { buildLoginUrl } from "./types";

export const REQUEST_ROUTE_HEADER = "x-deerflow-request-route";
const BASE = "https://deerflow.invalid";

/** Preserve user locators, excluding Next's transient RSC cache-busting query. */
export function requestReturnPath(url: Pick<URL, "pathname" | "search">) {
  const params = new URLSearchParams(url.search);
  params.delete("_rsc");
  return url.pathname + (params.size ? "?" + params.toString() : "");
}

/** A return address is navigation intent, never a workspace authorization. */
export function workspaceLoginHref(requestRoute: string | null) {
  const local = validateAuthNextPath(requestRoute);
  const pathname = local ? new URL(local, BASE).pathname : "";
  const target =
    pathname === "/workspace" || pathname.startsWith("/workspace/")
      ? local!
      : DEFAULT_AUTH_NEXT_PATH;
  return buildLoginUrl(target);
}

export function authenticatedEntryReturnPath(requestRoute: string | null) {
  const local = validateAuthNextPath(requestRoute);
  if (!local) return DEFAULT_AUTH_NEXT_PATH;
  const route = new URL(local, BASE);
  if (route.pathname !== "/login") return DEFAULT_AUTH_NEXT_PATH;
  const candidates = route.searchParams.getAll("next");
  if (candidates.length !== 1) return DEFAULT_AUTH_NEXT_PATH;
  const target = resolveAuthNextPath(candidates[0]);
  const path = new URL(target, BASE).pathname;
  if (
    path === "/login" ||
    path === "/setup" ||
    path === "/auth" ||
    path.startsWith("/auth/")
  )
    return DEFAULT_AUTH_NEXT_PATH;
  return target;
}
