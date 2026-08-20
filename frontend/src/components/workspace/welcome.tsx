"use client";

import { useSearchParams } from "next/navigation";
import { useEffect, useMemo } from "react";

import { AsterismMark } from "@/components/workspace/skins/asterism-mark";
import { useI18n } from "@/core/i18n/hooks";
import { useSkin } from "@/core/skins";
import { cn } from "@/lib/utils";

import { AuroraText } from "../ui/aurora-text";

let waved = false;

function WelcomeDescription({ children }: { children: string }) {
  return (
    <p className="max-w-full text-wrap break-words whitespace-pre-line">
      {children}
    </p>
  );
}

export function Welcome({
  className,
  mode,
}: {
  className?: string;
  mode?: "ultra" | "pro" | "thinking" | "flash";
}) {
  const { t } = useI18n();
  const { skin } = useSkin();
  const searchParams = useSearchParams();
  const observatory = skin === "observatory";
  const isUltra = useMemo(() => mode === "ultra", [mode]);
  const colors = useMemo(() => {
    if (isUltra) {
      return ["#efefbb", "#e9c665", "#e3a812"];
    }
    return ["var(--color-foreground)"];
  }, [isUltra]);
  useEffect(() => {
    waved = true;
  }, []);
  return (
    <div
      className={cn(
        "mx-auto flex w-full max-w-[640px] flex-col items-center justify-center gap-6 px-4 py-4 text-center sm:px-8",
        className,
      )}
    >
      <div className="max-w-full text-[2.6rem] leading-[1.15] font-bold tracking-tight">
        {searchParams.get("mode") === "skill" ? (
          `✨ ${t.welcome.createYourOwnSkill} ✨`
        ) : observatory ? (
          <>
            <div className="obs-welcome-kicker text-primary mb-2 flex items-center justify-center">
              <AsterismMark className="h-7 w-16" />
            </div>
            <h1 className="obs-welcome-title font-display text-[2.6rem] leading-[1.15] font-bold tracking-tight">
              {t.welcome.greeting}
            </h1>
          </>
        ) : (
          <div className="flex max-w-full flex-wrap items-center justify-center gap-2">
            <div className={cn("inline-block", !waved ? "animate-wave" : "")}>
              {isUltra ? "🚀" : "👋"}
            </div>
            <AuroraText colors={colors}>{t.welcome.greeting}</AuroraText>
          </div>
        )}
      </div>
      {searchParams.get("mode") === "skill" ? (
        <div className="text-muted-foreground max-w-[520px] text-[15px] leading-[1.75]">
          <WelcomeDescription>
            {t.welcome.createYourOwnSkillDescription}
          </WelcomeDescription>
        </div>
      ) : (
        <div
          className={cn(
            "text-muted-foreground max-w-[520px] text-[15px] leading-[1.75]",
            observatory && "obs-welcome-copy",
          )}
        >
          <WelcomeDescription>{t.welcome.description}</WelcomeDescription>
        </div>
      )}
    </div>
  );
}
