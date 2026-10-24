import { resolveStaticDemoArtifact } from "@/core/threads/static-demo";
import { checkCodeFile, getFileName } from "@/core/utils/files";
import { isWorkspaceId } from "@/core/workspaces/request-scope";

import { getTabularDelimiter } from "./preview";
import { urlOfArtifact } from "./utils";

/** Standalone route that renders a stored artifact with the app's own renderer. */
export const ARTIFACT_VIEWER_ROUTE = "/artifacts/view";

export type ArtifactViewerTarget = {
  filepath: string;
  threadId: string;
  isMock: boolean;
  workspaceId?: string;
};

/**
 * Language the artifacts panel renders a *stored* artifact with.
 *
 * `.skill` archives are ZIPs whose `SKILL.md` member is what the panel loads
 * (see `loadArtifactContent`), so they render as markdown like the panel does.
 * Kept here rather than inlined in the panel so the standalone viewer and the
 * panel cannot drift on what "this is markdown" means.
 */
export function resolveStoredArtifactLanguage(filepath: string) {
  if (filepath.endsWith(".skill")) {
    return "markdown";
  }
  return checkCodeFile(filepath).language;
}

/**
 * Target for the artifacts panel's "open in new window" action.
 *
 * Markdown and tabular files go to the in-app viewer route, which renders it with the same
 * components as the panel instead of handing the browser a `text/markdown`
 * response it can only show as raw source. Everything else keeps the raw
 * Gateway URL — notably HTML, SVG, and other XML documents, which the Gateway
 * deliberately serves as a download so active content never executes in the
 * application origin.
 */
export function resolveArtifactOpenURL({
  filepath,
  threadId,
  isMock = false,
  workspaceId,
}: {
  filepath: string;
  threadId: string;
  isMock?: boolean;
  workspaceId?: string;
}) {
  const language = resolveStoredArtifactLanguage(filepath);
  if (language !== "markdown" && getTabularDelimiter(language) === null) {
    return urlOfArtifact({ filepath, threadId, isMock, workspaceId });
  }
  return buildArtifactViewerURL({ filepath, threadId, isMock, workspaceId });
}

/**
 * Address of the viewer window for *target*.
 *
 * Unlike `resolveArtifactOpenURL` this never falls back to the Gateway URL:
 * callers that already are the viewer window — the auth guard rebuilding its
 * own address for a post-login return — need the route itself.
 */
export function buildArtifactViewerURL({
  filepath,
  threadId,
  isMock,
  workspaceId,
}: ArtifactViewerTarget) {
  if (workspaceId !== undefined && (!isWorkspaceId(workspaceId) || isMock))
    throw new Error("Invalid scoped artifact target");
  const params = new URLSearchParams({ path: filepath, thread_id: threadId });
  if (workspaceId !== undefined) params.set("workspace_id", workspaceId);
  if (isMock) {
    params.set("mock", "true");
  }
  return `${ARTIFACT_VIEWER_ROUTE}?${params.toString()}`;
}

/** Read a viewer target back out of the route's query string. */
export function parseArtifactViewerParams(
  params: URLSearchParams,
): ArtifactViewerTarget | null {
  const workspaceSelectors = params.getAll("workspace_id");
  const workspaceId = workspaceSelectors[0];
  if (
    workspaceSelectors.length > 1 ||
    (workspaceId !== undefined &&
      (!isWorkspaceId(workspaceId) || params.get("mock") === "true"))
  )
    return null;
  const filepath = params.get("path")?.trim();
  const threadId = params.get("thread_id")?.trim();
  if (!filepath || !threadId) {
    return null;
  }
  return {
    filepath,
    threadId,
    isMock: params.get("mock") === "true",
    ...(workspaceId === undefined ? {} : { workspaceId }),
  };
}

/**
 * Parse a Next.js `searchParams` record into a viewer target.
 *
 * A repeated query parameter arrives as an array; take the first value rather
 * than letting a second `?path=` appended to a shared link decide what the
 * window loads.
 */
export function parseArtifactViewerQuery(
  query: Record<string, string | string[] | undefined> | undefined,
): ArtifactViewerTarget | null {
  if (!query) {
    return null;
  }
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (key === "workspace_id" && Array.isArray(value) && value.length !== 1)
      return null;
    const first = Array.isArray(value) ? value[0] : value;
    if (first !== undefined) {
      params.set(key, first);
    }
  }
  return parseArtifactViewerParams(params);
}

/**
 * Browser-tab title for the viewer window.
 *
 * Applied through the route's `generateMetadata`, not `document.title`: the
 * App Router owns the title element and re-applies the layout's metadata over
 * anything an effect writes.
 */
export function artifactViewerTitle(filepath: string | undefined) {
  return filepath ? `${getFileName(filepath)} - DeerFlow` : "DeerFlow";
}

/**
 * Whether the viewer window has to sit behind the user-auth gate.
 *
 * Public `/showcase` threads render with `isMock`, and their artifacts are
 * served by the unauthenticated demo route, which answers only for an
 * allowlisted set of files. Gating those would bounce every logged-out
 * showcase visitor to /login for a document that is already public — and the
 * raw artifact URL this window replaced stayed reachable.
 *
 * The allowlist is the authority, not the flag: `mock=true` is caller-supplied
 * and on its own grants nothing, because a target the demo route would answer
 * with 404 still needs a session.
 */
export function requiresAuthenticatedViewer(target: ArtifactViewerTarget) {
  if (target.workspaceId !== undefined || !target.isMock) {
    return true;
  }
  const segments = target.filepath
    .replace(/^\/+/, "")
    .split("/")
    .map((segment) => encodeURIComponent(segment));
  return resolveStaticDemoArtifact(target.threadId, segments) === null;
}
