import { type ReactNode } from "react";

import { cn } from "@/lib/utils";

export type SectionProps = {
  id?: string;
  className?: string;
  index?: string;
  eyebrow?: ReactNode;
  title?: ReactNode;
  subtitle?: ReactNode;
  variant?: "default" | "soft";
  align?: "left" | "center";
  headerBorder?: boolean;
  children: ReactNode;
};

export function Section({
  id,
  className,
  index,
  eyebrow,
  title,
  subtitle,
  variant = "default",
  align = "left",
  headerBorder,
  children,
}: SectionProps) {
  const isCentered = align === "center";
  const hasKicker = Boolean(index) || Boolean(eyebrow);
  const showHeader = hasKicker || Boolean(title) || Boolean(subtitle);
  const hasHeaderBorder = headerBorder ?? !isCentered;

  return (
    <section
      id={id}
      className={cn(
        "w-full min-w-0 scroll-mt-[var(--df-header-height)] border-t border-[var(--df-border)] py-20 text-[var(--df-ink)] sm:py-24 lg:py-28",
        variant === "soft" ? "bg-[var(--df-bg-soft)]" : "bg-[var(--df-bg)]",
        className,
      )}
    >
      <div className="mx-auto w-full max-w-[1280px] min-w-0 px-4 sm:px-8 lg:px-12">
        {showHeader && (
          <header
            className={cn(
              isCentered
                ? "flex flex-col items-center text-center"
                : "grid grid-cols-1 gap-5 lg:grid-cols-12 lg:items-end lg:gap-8",
              hasHeaderBorder &&
                "mb-10 border-b border-[var(--df-border)] pb-8 sm:pb-10",
            )}
          >
            <div
              className={cn(
                "min-w-0",
                isCentered
                  ? "flex flex-col items-center"
                  : subtitle
                    ? "lg:col-span-7"
                    : "lg:col-span-12",
              )}
            >
              {hasKicker && (
                <p className="inline-flex flex-wrap items-center gap-2 font-mono text-xs font-medium tracking-[0.2em] text-[var(--df-accent)] uppercase">
                  {index && <span className="tabular-nums">{index}</span>}
                  {index && eyebrow && (
                    <span
                      className="text-[var(--df-border-strong)]"
                      aria-hidden="true"
                    >
                      /
                    </span>
                  )}
                  {eyebrow && <span>{eyebrow}</span>}
                </p>
              )}
              {title && (
                <h2
                  className={cn(
                    "font-landing-serif max-w-full text-3xl leading-[1.15] font-medium tracking-[-0.02em] break-words text-[var(--df-ink)] sm:text-4xl",
                    hasKicker && "mt-3",
                  )}
                >
                  {title}
                </h2>
              )}
            </div>

            {subtitle && (
              <div
                className={cn(
                  "min-w-0 text-sm leading-7 break-words text-[var(--df-muted-fg)] sm:text-base",
                  isCentered
                    ? "mx-auto mt-3 max-w-2xl"
                    : "max-w-xl lg:col-span-5 lg:max-w-none lg:pb-0.5",
                )}
              >
                {subtitle}
              </div>
            )}
          </header>
        )}

        <div
          className={cn(
            "w-full min-w-0",
            showHeader && !hasHeaderBorder && "mt-10",
          )}
        >
          {children}
        </div>
      </div>
    </section>
  );
}
