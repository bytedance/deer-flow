"use client";

import { ListIcon } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useI18n } from "@/core/i18n/hooks";
import type { ConversationChapter } from "@/core/messages/conversation-outline";
import { cn } from "@/lib/utils";

const MAX_OUTLINE_TICKS = 24;

type ConversationOutlineProps = {
  chapters: readonly ConversationChapter[];
  activeChapterId: string | null;
  onChapterSelect: (chapterId: string) => void;
};

type OutlineTick = {
  id: string;
  active: boolean;
};

function buildOutlineTicks(
  chapters: readonly ConversationChapter[],
  activeChapterIndex: number,
): OutlineTick[] {
  const tickCount = Math.min(chapters.length, MAX_OUTLINE_TICKS);

  return Array.from({ length: tickCount }, (_, tickIndex) => {
    const startIndex = Math.floor((tickIndex * chapters.length) / tickCount);
    const endIndex = Math.floor(
      ((tickIndex + 1) * chapters.length) / tickCount,
    );

    return {
      id: chapters[startIndex]?.id ?? `tick:${tickIndex}`,
      active: activeChapterIndex >= startIndex && activeChapterIndex < endIndex,
    };
  });
}

export function ConversationOutline({
  chapters,
  activeChapterId,
  onChapterSelect,
}: ConversationOutlineProps): ReactNode {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const activeItemRef = useRef<HTMLDivElement | null>(null);
  const activeChapterIndex = chapters.findIndex(
    (chapter) => chapter.id === activeChapterId,
  );
  const outlineTicks = buildOutlineTicks(chapters, activeChapterIndex);

  useEffect(() => {
    if (!open) {
      return;
    }
    activeItemRef.current?.scrollIntoView({ block: "nearest" });
  }, [activeChapterId, open]);

  return (
    <div className="pointer-events-none absolute top-1/2 right-2 z-20 -translate-y-1/2 sm:right-3">
      <DropdownMenu modal={false} open={open} onOpenChange={setOpen}>
        <DropdownMenuTrigger asChild>
          <Button
            aria-label={t.conversation.outlineLabel}
            className="bg-background/80 text-muted-foreground hover:text-foreground pointer-events-auto size-9 rounded-full border shadow-sm backdrop-blur-sm lg:h-auto lg:min-h-10 lg:w-7 lg:flex-col lg:gap-1 lg:px-1 lg:py-2"
            data-testid="conversation-outline-trigger"
            size="icon"
            type="button"
            variant="outline"
          >
            <ListIcon className="size-4 lg:hidden" />
            <span
              aria-hidden="true"
              className="hidden max-h-52 w-full flex-col items-center gap-1 overflow-hidden lg:flex"
            >
              {outlineTicks.map((tick) => (
                <span
                  key={tick.id}
                  className={cn(
                    "bg-muted-foreground/45 h-0.5 w-3 rounded-full transition-[width,background-color] motion-reduce:transition-none",
                    tick.active && "bg-foreground h-[3px] w-4",
                  )}
                />
              ))}
            </span>
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent
          align="center"
          className="border-border/80 bg-popover/95 max-h-[min(72vh,36rem)] w-72 overflow-y-auto rounded-2xl p-2 shadow-xl backdrop-blur-sm sm:max-h-[min(80vh,40rem)]"
          data-testid="conversation-outline-menu"
          side="left"
          sideOffset={8}
        >
          {chapters.map((chapter) => {
            const active = chapter.id === activeChapterId;
            return (
              <DropdownMenuItem
                key={chapter.id}
                ref={active ? activeItemRef : undefined}
                aria-current={active ? "location" : undefined}
                className={cn(
                  "items-start rounded-lg px-3 py-2 text-[15px] leading-5 whitespace-normal",
                  active && "bg-accent text-accent-foreground",
                )}
                title={chapter.title}
                onSelect={(event) => {
                  event.preventDefault();
                  onChapterSelect(chapter.id);
                }}
              >
                <span className="line-clamp-2 min-w-0 leading-5">
                  {chapter.title}
                </span>
              </DropdownMenuItem>
            );
          })}
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}
