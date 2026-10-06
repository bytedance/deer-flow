"use client";

import { LibraryBig, Plus } from "lucide-react";
import { useRouter } from "next/navigation";

import {
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
} from "@/components/ui/dropdown-menu";
import { useI18n } from "@/core/i18n/hooks";
import { useKnowledgeBases } from "@/core/knowledge/hooks";
import type { KnowledgeBase } from "@/core/knowledge/types";
import { env } from "@/env";

/**
 * Shared "Import to knowledge base" cascade submenu, embedded by both export
 * entry points (chat-window dropdown and recent-chat-list context menu) so
 * the KB picker stays identical. The caller owns message resolution and the
 * upload itself; this component only lists KBs and reports the pick.
 *
 * Renders nothing in static demo builds — there is no Gateway to upload to.
 */
export function KnowledgeBaseImportSubMenu({
  withSeparator = false,
  onSelect,
}: {
  /** Render a separator above the submenu (used by the chat-window dropdown). */
  withSeparator?: boolean;
  onSelect: (kb: KnowledgeBase) => void;
}) {
  const { t } = useI18n();
  const router = useRouter();
  const kbsQuery = useKnowledgeBases();

  if (env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true") {
    return null;
  }

  const kbs = kbsQuery.data ?? [];

  return (
    <>
      {withSeparator ? <DropdownMenuSeparator /> : null}
      <DropdownMenuSub>
        <DropdownMenuSubTrigger>
          <LibraryBig className="text-muted-foreground" />
          <span>{t.common.importToKnowledgeBase}</span>
        </DropdownMenuSubTrigger>
        <DropdownMenuSubContent className="max-h-72 overflow-y-auto">
          {kbsQuery.isPending ? (
            <DropdownMenuItem disabled>{t.common.loading}</DropdownMenuItem>
          ) : (
            <>
              {kbs.length === 0 ? (
                <DropdownMenuItem disabled>
                  {t.common.noKnowledgeBasesYet}
                </DropdownMenuItem>
              ) : (
                kbs.map((kb) => (
                  <DropdownMenuItem key={kb.id} onSelect={() => onSelect(kb)}>
                    <LibraryBig className="text-muted-foreground" />
                    <span className="truncate">{kb.name}</span>
                  </DropdownMenuItem>
                ))
              )}
              <DropdownMenuSeparator />
              <DropdownMenuItem
                onSelect={() => router.push("/workspace/knowledge")}
              >
                <Plus className="text-muted-foreground" />
                <span>{t.common.createKnowledgeBase}</span>
              </DropdownMenuItem>
            </>
          )}
        </DropdownMenuSubContent>
      </DropdownMenuSub>
    </>
  );
}
