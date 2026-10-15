import type { Metadata } from "next";
import { redirect } from "next/navigation";

import {
  ArtifactViewer,
  WorkspaceArtifactViewer,
} from "@/components/workspace/artifacts/artifact-viewer";
import {
  artifactViewerTitle,
  buildArtifactViewerURL,
  parseArtifactViewerQuery,
  requiresAuthenticatedViewer,
  type ArtifactViewerTarget,
} from "@/core/artifacts/viewer";
import { getServerSideUser } from "@/core/auth/server";
import { assertNever, buildLoginUrl } from "@/core/auth/types";
import { getI18n } from "@/core/i18n/server";
import { getServerSideWorkspaceCapability } from "@/core/workspaces/server";

const POST_LOGIN_FALLBACK = "/workspace";

type ArtifactViewerPageProps = {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
};

export async function generateMetadata({
  searchParams,
}: ArtifactViewerPageProps): Promise<Metadata> {
  const target = parseArtifactViewerQuery(await searchParams);
  return { title: artifactViewerTitle(target?.filepath) };
}

/**
 * Gate the window, keeping the artifact reachable across a re-login.
 *
 * `ARTIFACT_VIEWER_ROUTE` alone identifies nothing — the target is entirely in
 * the query string — so an expired session has to carry the full address into
 * `next`, or the user lands on the default workspace with no way back to the
 * document they opened.
 */
async function requireViewerAccess(target: ArtifactViewerTarget | null) {
  if (target && !requiresAuthenticatedViewer(target)) {
    return null;
  }
  const result = await getServerSideUser();
  switch (result.tag) {
    case "authenticated":
      return result.user;
    case "unauthenticated":
      redirect(
        buildLoginUrl(
          target ? buildArtifactViewerURL(target) : POST_LOGIN_FALLBACK,
        ),
      );
    case "needs_setup":
    case "system_setup_required":
      redirect("/setup");
    case "config_error":
      throw new Error(result.message);
    case "gateway_unavailable":
      // Retain this route; capability bootstrap below refuses unknown scope.
      return null;
    default:
      assertNever(result);
  }
}

export default async function ArtifactViewerPage({
  searchParams,
}: ArtifactViewerPageProps) {
  const target = parseArtifactViewerQuery(await searchParams);
  const user = await requireViewerAccess(target);

  if (!target) {
    const { t } = await getI18n();
    return (
      <main className="flex h-screen items-center justify-center p-6">
        <p className="text-muted-foreground text-sm">
          {t.artifactPreview.missingTarget}
        </p>
      </main>
    );
  }

  if (requiresAuthenticatedViewer(target)) {
    const capability = await getServerSideWorkspaceCapability().catch(
      () => null,
    );
    if (
      !capability ||
      (target.workspaceId !== undefined && !capability.enabled) ||
      (capability.enabled && (!capability.available || !user))
    ) {
      const { t } = await getI18n();
      return (
        <main
          role="alert"
          className="flex h-screen items-center justify-center p-6"
        >
          <p className="text-muted-foreground text-sm">
            {t.artifactPreview.unavailable}
          </p>
        </main>
      );
    }
    if (capability.enabled && user) {
      return (
        <WorkspaceArtifactViewer
          initialUser={user}
          workspaceId={target.workspaceId}
          filepath={target.filepath}
          threadId={target.threadId}
          isMock={target.isMock}
        />
      );
    }
  }

  return (
    <ArtifactViewer
      filepath={target.filepath}
      threadId={target.threadId}
      isMock={target.isMock}
    />
  );
}
