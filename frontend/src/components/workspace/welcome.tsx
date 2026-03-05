import { TriangleAlertIcon } from "lucide-react";
import { useMemo } from "react";
import { useSearchParams } from "react-router";

import { useI18n } from "@/core/i18n/hooks";
import { cn } from "@/lib/utils";

import { AuroraText } from "../ui/aurora-text";

export function Welcome({
  className,
  mode,
}: {
  className?: string;
  mode?: "ultra" | "pro" | "thinking" | "flash";
}) {
  const { t } = useI18n();
  const [searchParams] = useSearchParams();
  const isUltra = useMemo(() => mode === "ultra", [mode]);
  const colors = useMemo(() => {
    if (isUltra) {
      return ["#efefbb", "#e9c665", "#e3a812"];
    }
    return ["var(--color-foreground)"];
  }, [isUltra]);

  return (
    <div
      className={cn(
        "mx-auto flex w-full flex-col items-start gap-4 px-1 py-4",
        className,
      )}
    >
      {/* Logo */}
      <div className="mb-1">
        <img
          src="/images/gov.png"
          alt="Government building logo"
          className="size-8 object-contain"
        />
      </div>

      {/* Main headline - italic serif style, left-aligned */}
      <h1 className="max-w-[28ch] font-serif text-xl italic leading-tight tracking-tight text-foreground/90 sm:text-2xl 2xl:text-3xl">
        {searchParams.get("mode") === "skill" ? (
          t.welcome.createYourOwnSkill
        ) : (
          <>
            {isUltra ? (
              <AuroraText colors={colors}>{t.welcome.greeting}</AuroraText>
            ) : (
              <span>{t.welcome.greeting}</span>
            )}
          </>
        )}
      </h1>

      {/* Notice banner - dark card style */}
      <div className="flex w-full items-start gap-3 rounded-xl border border-border bg-card/80 px-5 py-4 text-left text-sm text-muted-foreground">
        <TriangleAlertIcon className="mt-0.5 size-4 shrink-0" />
        <p className="leading-relaxed">
          {searchParams.get("mode") === "skill" ? (
            t.welcome.createYourOwnSkillDescription.includes("\n") ? (
              <span className="whitespace-pre-wrap">
                {t.welcome.createYourOwnSkillDescription}
              </span>
            ) : (
              t.welcome.createYourOwnSkillDescription
            )
          ) : (
            <>
              {t.welcome.description}
              {" "}
              <a href="#" className="font-medium underline underline-offset-2 hover:text-foreground">
                Learn more
              </a>
              {" or "}
              <a href="#" className="font-medium underline underline-offset-2 hover:text-foreground">
                give us feedback
              </a>
              .
            </>
          )}
        </p>
      </div>
    </div>
  );
}
