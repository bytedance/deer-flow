import type { Metadata } from "next";
import { redirect } from "next/navigation";

import { ArtifactViewer } from "@/components/workspace/artifacts/artifact-viewer";
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
    return;
  }
  const result = await getServerSideUser();
  switch (result.tag) {
    case "authenticated":
      return;
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
      // Render anyway: the viewer surfaces its own load failure with a
      // download link, which beats bouncing a detached window to a page the
      // user did not ask for.
      return;
    default:
      assertNever(result);
  }
}

export default async function ArtifactViewerPage({
  searchParams,
}: ArtifactViewerPageProps) {
  const target = parseArtifactViewerQuery(await searchParams);
  await requireViewerAccess(target);

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

  return (
    <ArtifactViewer
      filepath={target.filepath}
      threadId={target.threadId}
      isMock={target.isMock}
    />
  );
}
