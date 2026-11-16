"use client";

import { GhostIcon } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { useIncognitoFeature } from "@/core/features/hooks";
import { useI18n } from "@/core/i18n/hooks";
import { env } from "@/env";

import { Tooltip } from "../tooltip";

/**
 * The ghost entry to a new incognito chat, sitting in the chat header's
 * top-right cluster. The sidebar carries no incognito item: the mode starts
 * from the surface it applies to.
 */
export function IncognitoEntry({ isNewThread }: { isNewThread: boolean }) {
  const { t } = useI18n();
  const { enabled } = useIncognitoFeature();
  // Only a blank new chat offers the entry: a saved conversation is already
  // committed to its visibility, and turning it into a temporary chat is not
  // something the storage boundary permits. A static demo has no Gateway, so
  // the entry would lead to a dead page, and an operator can disable new
  // incognito chats entirely.
  if (
    !isNewThread ||
    !enabled ||
    env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true"
  ) {
    return null;
  }
  return (
    <Tooltip content={t.incognito.entry}>
      <Button
        asChild
        className="text-muted-foreground"
        size="icon-sm"
        variant="ghost"
      >
        <Link
          aria-label={t.incognito.entry}
          href="/workspace/chats/new?incognito=true"
        >
          <GhostIcon />
        </Link>
      </Button>
    </Tooltip>
  );
}
