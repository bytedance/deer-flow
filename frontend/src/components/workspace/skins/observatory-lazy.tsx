"use client";

import dynamic from "next/dynamic";
import { useEffect } from "react";

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

export function ObservatoryLazy() {
  const { skin } = useSkin();

  useEffect(() => {
    if (skin !== "observatory") return;
    document.body.classList.add("obs-lock-scroll");
    return () => document.body.classList.remove("obs-lock-scroll");
  }, [skin]);

  if (skin !== "observatory") return null;
  return <ObservatoryOverlays />;
}
