"use client";

import { useAuth } from "@/core/auth/AuthProvider";
import { getFileExtension } from "@/core/utils/files";

import { useFrontendExtensions } from "./hooks";
import { activeFrontendExtensions } from "./registry";

/** Use the same viewer fence and exact extension matching in both readers. */
export function useArtifactPreviewRenderer(filepath: string) {
  const query = useFrontendExtensions();
  const { user } = useAuth();
  const match = user
    ? activeFrontendExtensions(query.data ?? [])
        .filter(
          ({ contribution }) =>
            !contribution.viewer_id || contribution.viewer_id === user.id,
        )
        .flatMap(({ contribution, extension }) =>
          (extension.artifactPreviews ?? []).map((renderer) => ({
            renderer,
            contribution,
          })),
        )
        .find(({ renderer }) =>
          renderer.extensions.includes(getFileExtension(filepath)),
        )
    : undefined;
  return { match, isLoading: query.isLoading, viewerId: user?.id };
}
