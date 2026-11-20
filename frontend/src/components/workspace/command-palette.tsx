"use client";

import {
  ArchiveIcon,
  Loader2Icon,
  SearchIcon,
  MessagesSquareIcon,
  KeyboardIcon,
  MessageSquarePlusIcon,
  SettingsIcon,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Command,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandShortcut,
} from "@/components/ui/command";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useI18n } from "@/core/i18n/hooks";
import {
  OPEN_SEARCH_EVENT,
  pathOfSearchHit,
  type SearchFilters,
} from "@/core/search/api";
import { useWorkspaceSearch } from "@/core/search/hooks";
import { useGlobalShortcuts } from "@/hooks/use-global-shortcuts";

import { useSettingsDialog } from "./settings";

export function CommandPalette() {
  const { t } = useI18n();
  const router = useRouter();
  const { openSettings } = useSettingsDialog();
  const [open, setOpen] = useState(false);
  const [input, setInput] = useState("");
  const [composing, setComposing] = useState(false);
  const [filters, setFilters] = useState<SearchFilters>({
    type: "all",
    includeArchived: true,
  });
  const commandMode = input.trimStart().startsWith(">");
  const search = useWorkspaceSearch(
    input,
    filters,
    open && !commandMode && !composing,
  );
  const busy = search.waiting || search.isPending || search.isFetching;
  useEffect(() => {
    const show = () => setOpen(true);
    window.addEventListener(OPEN_SEARCH_EVENT, show);
    return () => window.removeEventListener(OPEN_SEARCH_EVENT, show);
  }, []);
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  const [isMac, setIsMac] = useState(false);

  const handleNewChat = useCallback(() => {
    router.push("/workspace/chats/new");
    setOpen(false);
  }, [router]);

  const handleOpenSettings = useCallback(() => {
    setOpen(false);
    openSettings("appearance");
  }, [openSettings]);

  const handleShowShortcuts = useCallback(() => {
    setOpen(false);
    setShortcutsOpen(true);
  }, []);

  const shortcuts = useMemo(
    () => [
      { key: "k", meta: true, action: () => setOpen((o) => !o) },
      { key: "n", meta: true, shift: true, action: handleNewChat },
      { key: ",", meta: true, action: handleOpenSettings },
      { key: "/", meta: true, action: handleShowShortcuts },
    ],
    [handleNewChat, handleOpenSettings, handleShowShortcuts],
  );

  useGlobalShortcuts(shortcuts);

  useEffect(() => {
    setIsMac(navigator.userAgent.includes("Mac"));
  }, []);
  const metaKey = isMac ? "⌘" : "Ctrl+";
  const shiftKey = isMac ? "⇧" : "Shift+";

  return (
    <>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent
          className="overflow-hidden p-0 sm:max-w-2xl"
          showCloseButton={false}
        >
          <DialogTitle className="sr-only">
            {t.workspaceSearch.title}
          </DialogTitle>
          <DialogDescription className="sr-only">
            {t.workspaceSearch.description}
          </DialogDescription>
          <Command
            shouldFilter={false}
            onKeyDownCapture={(event) => {
              if (
                event.key === "Enter" &&
                (composing ||
                  event.nativeEvent.isComposing ||
                  event.nativeEvent.keyCode === 229)
              ) {
                event.preventDefault();
                event.stopPropagation();
              }
            }}
          >
            <CommandInput
              value={input}
              onValueChange={setInput}
              placeholder={t.workspaceSearch.placeholder}
              aria-label={t.workspaceSearch.title}
              onCompositionStart={() => setComposing(true)}
              onCompositionEnd={() => setComposing(false)}
            />
            {!commandMode && (
              <div className="flex flex-wrap items-center gap-1 border-b px-3 py-2">
                {(["all", "thread", "message"] as const).map((type) => (
                  <Button
                    key={type}
                    variant={filters.type === type ? "secondary" : "ghost"}
                    size="sm"
                    aria-pressed={filters.type === type}
                    onClick={() =>
                      setFilters((current) => ({ ...current, type }))
                    }
                  >
                    {type === "all"
                      ? t.workspaceSearch.all
                      : type === "thread"
                        ? t.workspaceSearch.threads
                        : t.workspaceSearch.messages}
                  </Button>
                ))}
                <label className="text-muted-foreground ml-auto flex items-center gap-2 px-1 text-sm">
                  <input
                    type="checkbox"
                    checked={filters.includeArchived}
                    onChange={(event) =>
                      setFilters((current) => ({
                        ...current,
                        includeArchived: event.target.checked,
                      }))
                    }
                  />
                  {t.workspaceSearch.includeArchived}
                </label>
              </div>
            )}
            <CommandList
              className="max-h-[min(60vh,480px)]"
              aria-busy={!commandMode && busy}
            >
              {!commandMode && (
                <>
                  {!search.supported && (
                    <p className="text-muted-foreground p-4 text-sm">
                      {t.workspaceSearch.unsupported}
                    </p>
                  )}
                  {search.supported && search.isError && (
                    <div role="alert" className="p-4 text-sm">
                      <p>{t.workspaceSearch.error}</p>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => void search.refetch()}
                      >
                        {t.workspaceSearch.retry}
                      </Button>
                    </div>
                  )}
                  {search.supported &&
                    !search.isError &&
                    busy &&
                    search.items.length === 0 && (
                      <div
                        role="status"
                        className="text-muted-foreground flex items-center gap-2 p-4 text-sm"
                      >
                        <Loader2Icon className="size-4 animate-spin" />
                        {t.workspaceSearch.searching}
                      </div>
                    )}
                  {search.data?.pages.some((page) => page.indexing) && (
                    <p
                      role="status"
                      className="text-muted-foreground px-4 py-2 text-sm"
                    >
                      {t.workspaceSearch.indexing}
                    </p>
                  )}
                  {input.trim() &&
                    search.data?.pages[0]?.messages_available === false && (
                      <p className="text-muted-foreground px-4 py-2 text-sm">
                        {t.workspaceSearch.unavailable}
                      </p>
                    )}
                  {(["thread", "message"] as const).map((type) => {
                    const hits = search.items.filter(
                      (hit) => hit.type === type,
                    );
                    if (!hits.length) return null;
                    return (
                      <CommandGroup
                        key={type}
                        heading={
                          type === "message"
                            ? t.workspaceSearch.messages
                            : input.trim()
                              ? t.workspaceSearch.threads
                              : t.workspaceSearch.recent
                        }
                      >
                        {hits.map((hit) => (
                          <CommandItem
                            key={`${hit.type}:${hit.thread_id}:${hit.message_id ?? ""}:${hit.seq ?? ""}`}
                            value={`${hit.type}:${hit.thread_id}:${hit.message_id ?? ""}:${hit.seq ?? ""}`}
                            className="items-start gap-3 px-3 py-3"
                            onSelect={() => {
                              router.push(pathOfSearchHit(hit));
                              setOpen(false);
                            }}
                          >
                            {type === "thread" ? (
                              <MessagesSquareIcon className="mt-0.5 size-4" />
                            ) : (
                              <SearchIcon className="mt-0.5 size-4" />
                            )}
                            <div className="min-w-0 flex-1">
                              <div className="flex items-center gap-2">
                                <span className="truncate font-medium">
                                  {hit.title.trim()
                                    ? hit.title
                                    : t.workspaceSearch.untitled}
                                </span>
                                {hit.archived && (
                                  <span className="text-muted-foreground flex shrink-0 items-center gap-1 text-xs">
                                    <ArchiveIcon className="size-3" />
                                    {t.workspaceSearch.archived}
                                  </span>
                                )}
                              </div>
                              {type === "message" && (
                                <p className="text-muted-foreground mt-1 line-clamp-2 text-sm">
                                  {hit.snippet.map((segment, index) =>
                                    segment.matched ? (
                                      <mark
                                        key={index}
                                        className="bg-foreground/10 text-foreground rounded-sm font-medium"
                                      >
                                        {segment.text}
                                      </mark>
                                    ) : (
                                      <span key={index}>{segment.text}</span>
                                    ),
                                  )}
                                </p>
                              )}
                              <div className="text-muted-foreground mt-1 flex gap-2 text-xs">
                                {type === "message" && (
                                  <span>
                                    {hit.role === "user"
                                      ? t.workspaceSearch.user
                                      : t.workspaceSearch.assistant}
                                  </span>
                                )}
                                <span>
                                  {hit.updated_at
                                    ? new Date(
                                        hit.updated_at,
                                      ).toLocaleDateString()
                                    : ""}
                                </span>
                              </div>
                            </div>
                          </CommandItem>
                        ))}
                      </CommandGroup>
                    );
                  })}
                  {!busy &&
                    !search.isError &&
                    search.supported &&
                    search.items.length === 0 &&
                    !search.data?.pages.some((page) => page.indexing) && (
                      <p className="text-muted-foreground p-6 text-center text-sm">
                        {t.workspaceSearch.empty}
                      </p>
                    )}
                  {search.hasNextPage && (
                    <CommandItem
                      value="load-more"
                      disabled={search.isFetchingNextPage}
                      onSelect={() => void search.fetchNextPage()}
                    >
                      {t.workspaceSearch.more}
                    </CommandItem>
                  )}
                </>
              )}
              {commandMode &&
                ![
                  t.sidebar.newChat,
                  t.common.settings,
                  t.shortcuts.keyboardShortcuts,
                ].some((label) =>
                  label
                    .toLocaleLowerCase()
                    .includes(
                      input.trimStart().slice(1).trim().toLocaleLowerCase(),
                    ),
                ) && (
                  <div
                    role="status"
                    className="text-muted-foreground py-8 text-center text-sm"
                  >
                    {t.workspaceSearch.empty}
                  </div>
                )}
              {(commandMode || !input.trim()) && (
                <CommandGroup heading={t.shortcuts.actions}>
                  {[
                    {
                      label: t.sidebar.newChat,
                      icon: MessageSquarePlusIcon,
                      action: handleNewChat,
                      shortcut: `${metaKey}${shiftKey}N`,
                    },
                    {
                      label: t.common.settings,
                      icon: SettingsIcon,
                      action: handleOpenSettings,
                      shortcut: `${metaKey},`,
                    },
                    {
                      label: t.shortcuts.keyboardShortcuts,
                      icon: KeyboardIcon,
                      action: handleShowShortcuts,
                      shortcut: `${metaKey}/`,
                    },
                  ]
                    .filter(
                      (action) =>
                        !commandMode ||
                        action.label
                          .toLocaleLowerCase()
                          .includes(
                            input
                              .trimStart()
                              .slice(1)
                              .trim()
                              .toLocaleLowerCase(),
                          ),
                    )
                    .map((action) => (
                      <CommandItem
                        key={action.label}
                        value={action.label}
                        onSelect={action.action}
                        className="px-3 py-3"
                      >
                        <action.icon className="size-4" />
                        {action.label}
                        <CommandShortcut>{action.shortcut}</CommandShortcut>
                      </CommandItem>
                    ))}
                </CommandGroup>
              )}
            </CommandList>
            <div className="text-muted-foreground border-t px-4 py-2 text-xs">
              {t.workspaceSearch.hint}
            </div>
          </Command>
        </DialogContent>
      </Dialog>

      <Dialog open={shortcutsOpen} onOpenChange={setShortcutsOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{t.shortcuts.keyboardShortcuts}</DialogTitle>
            <DialogDescription>
              {t.shortcuts.keyboardShortcutsDescription}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3 text-sm">
            {[
              { keys: `${metaKey}K`, label: t.shortcuts.openCommandPalette },
              { keys: `${metaKey}${shiftKey}N`, label: t.sidebar.newChat },
              { keys: `${metaKey}B`, label: t.shortcuts.toggleSidebar },
              { keys: `${metaKey},`, label: t.common.settings },
              {
                keys: `${metaKey}/`,
                label: t.shortcuts.keyboardShortcuts,
              },
            ].map(({ keys, label }) => (
              <div key={keys} className="flex items-center justify-between">
                <span className="text-muted-foreground">{label}</span>
                <kbd className="bg-muted text-muted-foreground rounded px-2 py-0.5 font-mono text-xs">
                  {keys}
                </kbd>
              </div>
            ))}
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
