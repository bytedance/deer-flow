import type { Metadata } from "next";

import { ArtifactViewer } from "@/components/workspace/artifacts/artifact-viewer";
import {
  artifactViewerTitle,
  parseArtifactViewerQuery,
} from "@/core/artifacts/viewer";
import { getI18n } from "@/core/i18n/server";

type ArtifactViewerPageProps = {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
};

export async function generateMetadata({
  searchParams,
}: ArtifactViewerPageProps): Promise<Metadata> {
  const target = parseArtifactViewerQuery(await searchParams);
  return { title: artifactViewerTitle(target?.filepath) };
}

export default async function ArtifactViewerPage({
  searchParams,
}: ArtifactViewerPageProps) {
  const target = parseArtifactViewerQuery(await searchParams);

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
