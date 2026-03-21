"use client";

import { useSearchParams } from "next/navigation";
import { useEffect, useMemo } from "react";

import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

import { AuroraText } from "../ui/aurora-text";

let waved = false;

export function Welcome({
  className,
  mode,
}: {
  className?: string;
  mode?: "ultra" | "pro" | "thinking" | "flash";
}) {
  const { t } = useI18n();
  const searchParams = useSearchParams();
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
        "mx-auto flex w-full flex-col items-center justify-center gap-6 px-10 py-12 text-center animate-fade-in",
        className,
      )}
    >
      <div className="flex flex-col items-center gap-4">
        <div className="bg-primary/10 text-primary flex size-16 items-center justify-center rounded-3xl shadow-xl glass-card border-white/10 transition-transform hover:rotate-12 duration-500">
          <span className="text-4xl">🦌</span>
        </div>
        
        <div className="text-4xl font-extrabold tracking-tight text-foreground sm:text-5xl">
          {searchParams.get("mode") === "skill" ? (
            <AuroraText colors={colors}>{t.welcome.createYourOwnSkill}</AuroraText>
          ) : (
            <div className="flex items-center justify-center gap-3">
              <AuroraText colors={colors}>{t.welcome.greeting}</AuroraText>
            </div>
          )}
        </div>
      </div>

      <div className="max-w-2xl">
        {searchParams.get("mode") === "skill" ? (
          <div className="text-muted-foreground/80 text-lg leading-relaxed">
            {t.welcome.createYourOwnSkillDescription.includes("\n") ? (
              <pre className="font-sans whitespace-pre-wrap">
                {t.welcome.createYourOwnSkillDescription}
              </pre>
            ) : (
              <p>{t.welcome.createYourOwnSkillDescription}</p>
            )}
          </div>
        ) : (
          <div className="text-muted-foreground/80 text-lg leading-relaxed">
            {t.welcome.description.includes("\n") ? (
              <pre className="font-sans whitespace-pre-wrap">{t.welcome.description}</pre>
            ) : (
              <p>{t.welcome.description}</p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
