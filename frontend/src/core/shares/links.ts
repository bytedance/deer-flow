import { shareArtifactURL, type SharedArtifact } from "./api";

/** Markdown may name a copied output, never a live workspace/upload endpoint. */
export function resolveShareArtifact(
  href: string,
  artifacts: SharedArtifact[],
  basePath = "",
) {
  let path = href.replace(/^sandbox:/, "");
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

export function sharedLink(
  href: string,
  token: string,
  artifacts: SharedArtifact[],
  basePath = "",
) {
  const artifact = resolveShareArtifact(href, artifacts, basePath);
  if (artifact) return shareArtifactURL(token, artifact.path);
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
