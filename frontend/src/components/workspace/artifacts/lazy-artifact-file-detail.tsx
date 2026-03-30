"use client";

import dynamic from "next/dynamic";

export const LazyArtifactFileDetail = dynamic(
  () =>
    import("./artifact-file-detail").then((mod) => ({
      default: mod.ArtifactFileDetail,
    })),
  {
    ssr: false,
  },
);
