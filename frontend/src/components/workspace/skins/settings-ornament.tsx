"use client";

import { useSkin } from "@/core/skins";
import { cn } from "@/lib/utils";

export function SettingsNavPulse({ active }: { active?: boolean }) {
  const { skin } = useSkin();
  if (skin !== "observatory") return null;
  return (
    <span
      className={cn("obs-nav-pulse", active && "is-active")}
      aria-hidden="true"
    />
  );
}
