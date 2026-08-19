"use client";

import { useTheme } from "next-themes";

import { useI18n } from "@/core/i18n/hooks";
import { useSkin } from "@/core/skins";
import { applyObservatoryTheme } from "@/core/skins/theme-transition";
import { cn } from "@/lib/utils";

export function SkyToggle({ className }: { className?: string }) {
  const { skin } = useSkin();
  const { resolvedTheme, setTheme } = useTheme();
  const { t } = useI18n();
  if (skin !== "observatory") return null;

  const isDark = resolvedTheme === "dark";
  return (
    <div className={cn("obs-sky-tools", className)}>
      <span className="obs-meter" aria-hidden="true">
        <b />
        <b />
        <b />
        <b />
      </span>
      <button
        type="button"
        className="obs-sky-toggle"
        aria-label={t.skins.observatory.toggleSky}
        onClick={() => {
          applyObservatoryTheme(
            isDark ? "light" : "dark",
            resolvedTheme,
            setTheme,
          );
        }}
      >
        <span className="orb" />
        <span className="sky-dust" />
      </button>
      <span className="obs-sky-label">
        {isDark
          ? t.skins.observatory.nightLabel
          : t.skins.observatory.dawnLabel}
      </span>
    </div>
  );
}
