import { shareArtifactURL, type SharedArtifact } from "./api";

/** Markdown may name a copied output, never a live workspace/upload endpoint. */
export function resolveShareArtifact(
  href: string,
  artifacts: SharedArtifact[],
  basePath = "",
) {
  // Split URL syntax before decoding: %23 and %3F are filename characters.
  let path = href.split(/[?#]/, 1)[0]!.replace(/^sandbox:/, "");
  try {
    path = decodeURIComponent(path);
  } catch {
    return undefined;
  }
  if (path.startsWith("/mnt/user-data/outputs/")) path = path.slice(23);
  else if (path.startsWith("mnt/user-data/outputs/")) path = path.slice(22);
  else if (
    path.startsWith("/") ||
    /^[a-zA-Z][\w+.-]*:/.test(path) ||
    path.includes("\\")
  )
    return undefined;
  else path = `${basePath}${path}`;
  const normalized: string[] = [];
  for (const part of path.split("/")) {
    if (part === "..") {
      if (!normalized.length) return undefined;
      normalized.pop();
    } else if (part && part !== ".") normalized.push(part);
  }
  return artifacts.find((artifact) => artifact.path === normalized.join("/"));
}

/** Build an inline URL only for a file in the snapshot manifest. */
export function sharedArtifactLink(
  href: string,
  token: string,
  artifacts: SharedArtifact[],
  basePath = "",
) {
  const artifact = resolveShareArtifact(href, artifacts, basePath);
  if (!artifact) return undefined;

  const [, query = "", fragment = ""] =
    /^[^?#]*(\?[^#]*)?(#[\s\S]*)?$/.exec(href) ?? [];
  // The Gateway reserves `download` for its explicit download action. Keep
  // other query entries in their original encoding and leave fragments intact.
  const inlineQuery = query
    .slice(1)
    .split("&")
    .filter((part) => !new URLSearchParams(`?${part}`).has("download"))
    .join("&");
  return (
    shareArtifactURL(token, artifact.path) +
    (inlineQuery ? `?${inlineQuery}` : "") +
    fragment
  );
}

export function sharedLink(
  href: string,
  token: string,
  artifacts: SharedArtifact[],
  basePath = "",
) {
  const copied = sharedArtifactLink(href, token, artifacts, basePath);
  if (copied) return copied;
  try {
    const url = new URL(href);
    if (
      ["https:", "http:"].includes(url.protocol) &&
      url.origin !== window.location.origin &&
      !url.username &&
      !url.password
    )
      return url.href;
  } catch {
    /* Non-URL text remains visible without navigation. */
  }
  return undefined;
}
