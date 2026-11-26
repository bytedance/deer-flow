import { type ReactNode } from "react";

import { cn } from "@/lib/utils";

export type SectionProps = {
  id?: string;
  className?: string;
  eyebrow?: ReactNode;
  title: ReactNode;
  subtitle?: ReactNode;
  variant?: "default" | "soft";
  align?: "left" | "center";
  headerBorder?: boolean;
  children: ReactNode;
};

export function Section({
  id,
  className,
  eyebrow,
  title,
  subtitle,
  variant = "default",
  align = "left",
  headerBorder = false,
  children,
}: SectionProps) {
  const isCentered = align === "center";

  return (
    <section
      id={id}
      className={cn(
        "w-full min-w-0 scroll-mt-[var(--df-header-height)] border-t border-[var(--df-border)] py-20 text-[var(--df-ink)] sm:py-28",
        variant === "soft" ? "bg-[var(--df-bg-soft)]" : "bg-[var(--df-bg)]",
        className,
      )}
    >
      <div className="mx-auto w-full max-w-[1280px] min-w-0 px-4 sm:px-8 lg:px-12">
        <header
          className={cn(
            "flex flex-col",
            isCentered ? "items-center text-center" : "items-start text-left",
            headerBorder && "border-b border-[var(--df-border)] pb-8",
          )}
        >
          {eyebrow && (
            <p className="font-mono text-xs font-medium tracking-[0.24em] text-[var(--df-accent)] uppercase">
              {eyebrow}
            </p>
          )}
          <h2
            className={cn(
              "max-w-full text-2xl font-semibold tracking-tight break-words text-[var(--df-ink)] sm:text-3xl",
              eyebrow && "mt-3",
            )}
          >
            {title}
          </h2>
          {subtitle && (
            <div
              className={cn(
                "mt-3 max-w-2xl text-sm leading-7 break-words text-[var(--df-muted-fg)] sm:text-base",
                isCentered && "mx-auto",
              )}
            >
              {subtitle}
            </div>
          )}
        </header>
        <div className="mt-10 w-full min-w-0">{children}</div>
      </div>
    </section>
  );
}
