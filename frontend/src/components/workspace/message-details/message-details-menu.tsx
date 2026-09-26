"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

export interface MessageDetailsMenuEntry {
  id: string;
  title: string;
  subtitle?: string;
  onSelect: (origin?: HTMLElement) => void;
}

export function MessageDetailsMenu({
  label,
  title,
  icon,
  entries,
}: {
  label: string;
  title: string;
  icon: ReactNode;
  entries: MessageDetailsMenuEntry[];
}) {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const selectedEntryRef = useRef(false);
  const interaction = useRef<"hover" | "press">("press");
  const openTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const clearTimers = () => {
    if (openTimer.current) clearTimeout(openTimer.current);
    if (closeTimer.current) clearTimeout(closeTimer.current);
    openTimer.current = null;
    closeTimer.current = null;
  };
  useEffect(
    () => () => {
      if (openTimer.current) clearTimeout(openTimer.current);
      if (closeTimer.current) clearTimeout(closeTimer.current);
    },
    [],
  );
  const enter = (pointerType: string) => {
    if (pointerType !== "mouse") return;
    clearTimers();
    if (!open) {
      openTimer.current = setTimeout(() => {
        interaction.current = "hover";
        setOpen(true);
        openTimer.current = null;
      }, 120);
    }
  };
  const leave = (pointerType: string) => {
    if (pointerType !== "mouse") return;
    clearTimers();
    if (interaction.current === "hover") {
      closeTimer.current = setTimeout(() => {
        setOpen(false);
        closeTimer.current = null;
      }, 180);
    }
  };
  const press = () => {
    clearTimers();
    interaction.current = "press";
  };

  if (entries.length === 0) return null;
  return (
    <DropdownMenu
      modal={false}
      open={open}
      onOpenChange={(nextOpen) => {
        clearTimers();
        if (nextOpen) selectedEntryRef.current = false;
        setOpen(nextOpen);
      }}
    >
      <DropdownMenuTrigger asChild>
        <Button
          ref={triggerRef}
          size="icon-sm"
          variant="ghost"
          aria-label={label}
          onPointerEnter={(event) => enter(event.pointerType)}
          onPointerLeave={(event) => leave(event.pointerType)}
          onPointerDown={press}
          onKeyDown={press}
        >
          {icon}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align="start"
        side="top"
        className="w-64 max-w-[calc(100vw-2rem)] rounded-xl p-2"
        onPointerEnter={(event) => enter(event.pointerType)}
        onPointerLeave={(event) => leave(event.pointerType)}
        // Radix forwards this FocusScope hook at runtime but omits it from
        // DropdownMenuContent's public type; keep hover from moving composer focus.
        {...{
          onOpenAutoFocus: (event: Event) => {
            if (interaction.current === "hover") event.preventDefault();
          },
        }}
        onCloseAutoFocus={(event) => {
          if (interaction.current === "hover" || selectedEntryRef.current)
            event.preventDefault();
        }}
      >
        <DropdownMenuLabel className="text-muted-foreground px-2 text-xs font-medium">
          {title}
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        {entries.map((entry) => (
          <DropdownMenuItem
            key={entry.id}
            className="group cursor-pointer justify-between gap-3 rounded-lg py-2 focus:bg-transparent"
            onSelect={() => {
              selectedEntryRef.current = true;
              entry.onSelect(triggerRef.current ?? undefined);
            }}
          >
            <span className="min-w-0 truncate text-sm underline-offset-4 group-hover:underline group-focus:underline">
              {entry.title}
            </span>
            {entry.subtitle && (
              <span className="text-muted-foreground shrink-0 text-xs">
                {entry.subtitle}
              </span>
            )}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
