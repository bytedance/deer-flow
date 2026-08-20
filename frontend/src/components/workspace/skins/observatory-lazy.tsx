"use client";

import dynamic from "next/dynamic";

import { useSkin } from "@/core/skins";

// Lazy-load observatory-only components so classic users never download
// these JS chunks (PointerPlay, CornerConstellations, IdleMeteors, etc).
const ObservatoryOverlays = dynamic(
  () =>
    import("./observatory-overlays").then((m) => ({
      default: m.ObservatoryOverlays,
    })),
  { ssr: false },
);

const WorkspaceIntro = dynamic(
  () =>
    import("./workspace-intro").then((m) => ({
      default: m.WorkspaceIntro,
    })),
  { ssr: false },
);

export function ObservatoryLazy() {
  const { skin } = useSkin();
  if (skin !== "observatory") return null;
  return (
    <>
      <WorkspaceIntro />
      <ObservatoryOverlays />
    </>
  );
}
