"use client";

import { MoreHorizontal, Trash2 } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import { useI18n } from "@/core/i18n/hooks";
import { useDeleteThread, useThreads } from "@/core/threads/hooks";
import { pathOfThread, titleOfThread } from "@/core/threads/utils";
import { formatTimeAgo } from "@/core/utils/datetime";
import { env } from "@/env";

export default function ChatsPage() {
  const { t } = useI18n();
  const { data: threads } = useThreads();
  const { mutate: deleteThread } = useDeleteThread();
  const [search, setSearch] = useState("");

  useEffect(() => {
    document.title = `${t.pages.chats} - ${t.pages.appName}`;
  }, [t.pages.chats, t.pages.appName]);

  const filteredThreads = useMemo(() => {
    return threads?.filter((thread) => {
      return titleOfThread(thread).toLowerCase().includes(search.toLowerCase());
    });
  }, [threads, search]);
  return (
    <WorkspaceContainer>
      <WorkspaceHeader></WorkspaceHeader>
      <WorkspaceBody>
        <div className="flex size-full flex-col">
          <header className="flex shrink-0 items-center justify-center pt-8">
            <Input
              type="search"
              className="h-12 w-full max-w-(--container-width-md) text-xl"
              placeholder={t.chats.searchChats}
              autoFocus
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </header>
          <main className="min-h-0 flex-1">
            <ScrollArea className="size-full py-4">
              <div className="mx-auto flex size-full max-w-(--container-width-md) flex-col">
                {filteredThreads?.map((thread) => (
                  <div
                    key={thread.thread_id}
                    className="group/chat-row flex items-center gap-2 border-b p-4"
                  >
                    <Link
                      className="min-w-0 flex-1"
                      href={pathOfThread(thread)}
                    >
                      <div className="flex min-w-0 flex-col gap-2">
                        <div>{titleOfThread(thread)}</div>
                        {thread.updated_at && (
                          <div className="text-muted-foreground text-sm">
                            {formatTimeAgo(thread.updated_at)}
                          </div>
                        )}
                      </div>
                    </Link>
                    {env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY !== "true" && (
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="size-8 opacity-100 md:opacity-0 md:group-hover/chat-row:opacity-100 md:focus-visible:opacity-100 md:data-[state=open]:opacity-100"
                          >
                            <MoreHorizontal />
                            <span className="sr-only">{t.common.more}</span>
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
                          <DropdownMenuItem
                            variant="destructive"
                            onSelect={() =>
                              deleteThread({ threadId: thread.thread_id })
                            }
                          >
                            <Trash2 />
                            <span>{t.common.delete}</span>
                          </DropdownMenuItem>
                        </DropdownMenuContent>
                      </DropdownMenu>
                    )}
                  </div>
                ))}
              </div>
            </ScrollArea>
          </main>
        </div>
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}
