"use client";

import { Portal } from "@headlessui/react";
import { GitHubLogoIcon } from "@radix-ui/react-icons";
import { ArrowUpRight, MenuIcon } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { type ReactNode, useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import {
  type LandingLocale,
  useOptionalLandingLocale,
} from "@/core/i18n/landing";
import { cn } from "@/lib/utils";

import { LanguageSwitch } from "./language-switch";
import { ThemeToggle } from "./theme-toggle";

export type MobileNavLink = {
  href: string;
  label: string;
  external?: boolean;
};

export type MobileNavGroup = {
  title: string;
  items: MobileNavLink[];
};

export type MobileNavProps = {
  links: MobileNavLink[];
  groups?: MobileNavGroup[];
  search?: ReactNode;
  locale?: LandingLocale;
  triggerClassName?: string;
  showActions?: boolean;
};

export function MobileNav({
  links,
  groups,
  search,
  locale,
  triggerClassName,
  showActions = false,
}: MobileNavProps) {
  const pathname = usePathname();
  const { locale: activeLocale } = useOptionalLandingLocale(locale);
  const contentRef = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  // Close on navigation (e.g. picking a search result). The docs layout keeps
  // this component mounted across pages, so reset during render rather than
  // only hiding the sheet while the path differs.
  const [openedPath, setOpenedPath] = useState(pathname);
  if (pathname !== openedPath) {
    setOpenedPath(pathname);
    setOpen(false);
  }

  useEffect(() => {
    if (!open) return;
    // Same-page search results only change the hash.
    const close = () => setOpen(false);
    window.addEventListener("hashchange", close);
    return () => window.removeEventListener("hashchange", close);
  }, [open]);

  const getStartedLabel = activeLocale === "zh-CN" ? "开始使用" : "Get Started";
  const githubLabel =
    activeLocale === "zh-CN" ? "访问 GitHub" : "Star on GitHub";

  const renderLink = (link: MobileNavLink) => {
    const linkClassName =
      "flex min-h-11 items-center justify-between rounded-lg px-2.5 text-sm font-medium text-[var(--df-text-soft)] transition-colors hover:bg-[var(--df-muted)] hover:text-[var(--df-ink)]";
    if (link.external) {
      return (
        <a
          key={link.href}
          href={link.href}
          target="_blank"
          rel="noopener noreferrer"
          onClick={() => setOpen(false)}
          className={linkClassName}
        >
          <span>{link.label}</span>
          <ArrowUpRight
            className="size-3.5 text-[var(--df-muted-fg)]"
            aria-hidden="true"
          />
        </a>
      );
    }
    return (
      <Link
        key={link.href}
        href={link.href}
        onClick={() => setOpen(false)}
        className={linkClassName}
      >
        <span>{link.label}</span>
      </Link>
    );
  };

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger asChild className={cn("xl:hidden", triggerClassName)}>
        <Button
          variant="ghost"
          size="icon"
          aria-label="Open menu"
          className="h-9 w-9 rounded-full text-[var(--df-muted-fg)] hover:bg-[var(--df-muted)] hover:text-[var(--df-ink)]"
        >
          <MenuIcon className="size-5" aria-hidden="true" />
        </Button>
      </SheetTrigger>
      <SheetContent
        ref={contentRef}
        side="right"
        className="w-72 overflow-y-auto border-l border-[var(--df-border)] bg-[var(--df-bg)] text-[var(--df-ink)] sm:w-80"
        aria-describedby={undefined}
        onClick={(event) => {
          // A result at the current hash emits neither pathname nor hashchange.
          // Bubble after the result's own navigation handler has run.
          if (
            event.target instanceof Element &&
            event.target.closest(".nextra-search-results a[href]")
          ) {
            setOpen(false);
          }
        }}
        onKeyDownCapture={(event) => {
          if (event.key !== "Enter" || !(event.target instanceof Element))
            return;
          const activeId = event.target.getAttribute("aria-activedescendant");
          const option = activeId ? document.getElementById(activeId) : null;
          if (
            !option?.matches(".nextra-search-results a[href]") ||
            !contentRef.current?.contains(option)
          )
            return;
          // Headless UI stops Enter propagation. Let its selection handler run
          // first, and close only if it handled the key (not IME composition).
          const nativeEvent = event.nativeEvent;
          // A microtask can run between native capture and bubble listeners.
          window.setTimeout(() => {
            if (nativeEvent.defaultPrevented && !nativeEvent.isComposing) {
              setOpen(false);
            }
          }, 0);
        }}
      >
        <SheetHeader className="border-b border-[var(--df-border)] pb-3">
          <SheetTitle className="font-landing-serif flex items-center gap-2 text-xl font-medium tracking-[-0.02em] text-[var(--df-ink)]">
            <svg
              viewBox="0 0 24 24"
              fill="none"
              aria-hidden="true"
              className="size-5 shrink-0 text-[var(--df-ink)]"
            >
              <path
                d="M4.5 18.5C7.2 16.5 9.6 16.5 12 18C14.4 19.5 16.8 19.5 19.5 17.5"
                stroke="var(--df-accent)"
                strokeWidth="1.75"
                strokeLinecap="round"
              />
              <path
                d="M12 15.25V10.5M12 10.5L7.5 6.5M12 10.5L16.5 6.5M9.5 8.25L8 4.5M14.5 8.25L16 4.5"
                stroke="currentColor"
                strokeWidth="1.65"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
              <circle cx="12" cy="5.25" r="1.35" fill="var(--df-accent)" />
            </svg>
            <span>DeerFlow</span>
          </SheetTitle>
        </SheetHeader>
        {search && (
          // Radix's modal scroll lock only allows descendants of its content.
          <Portal.Group as="div" target={contentRef}>
            <div className="px-4 [&_input]:h-11">{search}</div>
          </Portal.Group>
        )}
        <nav className="flex flex-col gap-5 px-4 pb-6">
          {groups && groups.length > 0 ? (
            groups.map((group) => (
              <div key={group.title} className="flex flex-col gap-1">
                <p className="px-2.5 font-mono text-[10px] font-medium tracking-[0.18em] text-[var(--df-muted-fg)] uppercase">
                  {group.title}
                </p>
                <div className="flex flex-col">
                  {group.items.map(renderLink)}
                </div>
              </div>
            ))
          ) : (
            <div className="flex flex-col gap-1">{links.map(renderLink)}</div>
          )}

          {showActions && (
            <div className="mt-2 flex flex-col gap-3 border-t border-[var(--df-border)] pt-4">
              <div className="flex items-center justify-between gap-2">
                <LanguageSwitch locale={activeLocale} />
                <ThemeToggle locale={activeLocale} />
              </div>
              <a
                href="https://github.com/bytedance/deer-flow"
                target="_blank"
                rel="noopener noreferrer"
                onClick={() => setOpen(false)}
                className="inline-flex min-h-11 items-center justify-center gap-2 rounded-full border border-[var(--df-border-strong)] bg-[var(--df-panel)] px-4 text-sm font-medium text-[var(--df-ink)] transition-colors hover:bg-[var(--df-muted)]"
              >
                <GitHubLogoIcon className="size-4" aria-hidden="true" />
                <span>{githubLabel}</span>
              </a>
              <Link
                href="/workspace"
                onClick={() => setOpen(false)}
                className="inline-flex min-h-11 items-center justify-center rounded-full bg-[var(--df-cta)] px-4 text-sm font-medium text-[var(--df-cta-fg)] transition-colors hover:bg-[var(--df-cta-hover)]"
              >
                {getStartedLabel}
              </Link>
            </div>
          )}
        </nav>
      </SheetContent>
    </Sheet>
  );
}
