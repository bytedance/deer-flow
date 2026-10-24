import type { LinkProps } from "next/link";

import { isWorkspaceId } from "./request-scope";

type Href = LinkProps["href"];
function isWorkspacePath(pathname: string) {
  return pathname === "/workspace" || pathname.startsWith("/workspace/");
}

/** Empty marks an invalid explicit selector; only absence means personal default. */
export function workspaceSelector(params: Pick<URLSearchParams, "getAll">) {
  const values = params.getAll("workspace_id");
  if (!values.length) return undefined;
  return values.length === 1 && isWorkspaceId(values[0]!) ? values[0] : "";
}

export function workspaceHref(href: string, selector?: string): string;
export function workspaceHref(href: Href, selector?: string): Href;
/** Preserve explicit locators and never put a private locator into a foreign URL. */
export function workspaceHref(href: Href, selector?: string): Href {
  if (selector === undefined) return href;
  if (typeof href === "string") {
    if (!href.startsWith("/") || href.startsWith("//")) return href;
    const url = new URL(href, "https://workspace.invalid");
    if (
      url.origin !== "https://workspace.invalid" ||
      !isWorkspacePath(url.pathname) ||
      url.searchParams.has("workspace_id")
    )
      return href;
    url.searchParams.set("workspace_id", selector);
    return url.pathname + url.search + url.hash;
  }
  if (
    href.host ||
    href.hostname ||
    href.protocol ||
    href.auth ||
    href.href ||
    !href.pathname
  )
    return href;
  if (!href.pathname.startsWith("/") || href.pathname.startsWith("//"))
    return href;
  const url = new URL(href.pathname, "https://workspace.invalid");
  if (
    url.origin !== "https://workspace.invalid" ||
    !isWorkspacePath(url.pathname)
  )
    return href;
  if (href.search) {
    const params = new URLSearchParams(href.search);
    if (params.has("workspace_id")) return href;
    params.set("workspace_id", selector);
    return { ...href, search: "?" + params.toString() };
  }
  if (typeof href.query === "string") {
    const params = new URLSearchParams(href.query);
    if (params.has("workspace_id")) return href;
    params.set("workspace_id", selector);
    return { ...href, query: params.toString() };
  }
  if (href.query && Object.hasOwn(href.query, "workspace_id")) return href;
  return { ...href, query: { ...href.query, workspace_id: selector } };
}
