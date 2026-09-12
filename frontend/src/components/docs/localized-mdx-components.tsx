"use client";

import { Anchor, Cards as NextraCards } from "nextra/components";
import type { ComponentProps } from "react";

import { cn } from "@/lib/utils";

import { useDocsLanguage } from "./docs-language-context";
import { localizeDocsHref } from "./localized-links";

const DOCS_LINK_CLASS_NAME =
  "x:text-primary-600 x:underline x:hover:no-underline x:decoration-from-font x:[text-underline-position:from-font]";

export function LocalizedDocsLink({
  href,
  className,
  ...props
}: ComponentProps<typeof Anchor>) {
  const lang = useDocsLanguage();
  const localizedHref =
    typeof href === "string" ? localizeDocsHref(href, lang) : href;

  return (
    <Anchor
      {...props}
      className={cn(DOCS_LINK_CLASS_NAME, className)}
      href={localizedHref}
    />
  );
}

export function LocalizedCard({
  href,
  ...props
}: ComponentProps<typeof NextraCards.Card>) {
  const lang = useDocsLanguage();
  return <NextraCards.Card {...props} href={localizeDocsHref(href, lang)} />;
}
