"use client";

import { useParams } from "next/navigation";
import { Anchor, Cards as NextraCards } from "nextra/components";
import type { ComponentProps } from "react";

import { cn } from "@/lib/utils";

import { localizeDocsHref } from "./localized-links";

const DOCS_LINK_CLASS_NAME =
  "x:text-primary-600 x:underline x:hover:no-underline x:decoration-from-font x:[text-underline-position:from-font]";

function useDocumentLanguage(): string | undefined {
  const { lang } = useParams<{ lang?: string }>();
  return lang;
}

export function LocalizedDocsLink({
  href,
  className,
  ...props
}: ComponentProps<typeof Anchor>) {
  const lang = useDocumentLanguage();
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
  const lang = useDocumentLanguage();
  return <NextraCards.Card {...props} href={localizeDocsHref(href, lang)} />;
}
