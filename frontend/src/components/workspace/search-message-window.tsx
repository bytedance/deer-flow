"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowDownIcon, ArrowUpIcon, Loader2Icon } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState, type ComponentProps } from "react";
import type { ImgHTMLAttributes } from "react";

import { Button } from "@/components/ui/button";
import { resolveMessageImageURL } from "@/core/artifacts/utils";
import { useAuth } from "@/core/auth/AuthProvider";
import { useI18n } from "@/core/i18n/hooks";
import { fetchMessageWindow } from "@/core/search/api";
import { cn } from "@/lib/utils";

import { MarkdownContent } from "./messages/markdown-content";
import { createMarkdownLinkComponent } from "./messages/markdown-link";
import { MessageList } from "./messages/message-list";

export function SearchableMessageList(
  props: ComponentProps<typeof MessageList>,
) {
  const params = useSearchParams();
  const messageId = params.get("message");
  const seq = Number(params.get("message_seq"));
  if (!messageId) return <MessageList {...props} />;
  return (
    <SearchMessageWindow
      key={`${props.threadId}:${messageId}:${seq}`}
      threadId={props.threadId}
      messageId={messageId}
      seq={Number.isSafeInteger(seq) && seq > 0 ? seq : undefined}
    />
  );
}

function SearchMessageWindow({
  threadId,
  messageId,
  seq,
}: {
  threadId: string;
  messageId: string;
  seq?: number;
}) {
  const { t } = useI18n();
  const { user } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const target = useRef<HTMLElement | null>(null);
  const viewport = useRef<HTMLDivElement | null>(null);
  const [anchor, setAnchor] = useState({ messageId, seq });
  const query = useQuery({
    queryKey: [
      "search-message-window",
      user?.id,
      threadId,
      anchor.messageId,
      anchor.seq,
    ],
    queryFn: ({ signal }) =>
      fetchMessageWindow(threadId, anchor.messageId, anchor.seq, signal),
    retry: false,
    refetchOnWindowFocus: false,
    staleTime: 0,
  });
  useEffect(() => {
    if (query.data && target.current && viewport.current) {
      viewport.current.scrollTop =
        target.current.offsetTop -
        (viewport.current.clientHeight - target.current.offsetHeight) / 2;
    }
  }, [query.data]);
  const returnToLatest = () => {
    const next = new URLSearchParams(params.toString());
    next.delete("message");
    next.delete("message_seq");
    const queryString = next.toString();
    router.replace(`${pathname}${queryString ? `?${queryString}` : ""}`, {
      scroll: false,
    });
  };
  const markdownComponents = {
    a: createMarkdownLinkComponent(threadId),
    img: ({ src, alt, ...props }: ImgHTMLAttributes<HTMLImageElement>) => (
      <img
        {...props}
        src={
          typeof src === "string"
            ? resolveMessageImageURL(src, threadId, [])
            : src
        }
        alt={alt}
        loading="lazy"
      />
    ),
  };
  const data = query.data;
  const first = data?.messages[0];
  const last = data?.messages.at(-1);
  return (
    <section
      className="flex h-full min-h-0 w-full flex-1 flex-col overflow-hidden pt-12"
      aria-label={t.workspaceSearch.context}
      data-testid="search-message-window"
    >
      <div className="bg-background flex shrink-0 items-center justify-between gap-2 border-b px-4 py-2 text-sm">
        <span>{t.workspaceSearch.context}</span>
        <Button variant="ghost" size="sm" onClick={returnToLatest}>
          {t.workspaceSearch.returnToLatest}
        </Button>
      </div>
      <div
        ref={viewport}
        className="relative min-h-0 flex-1 overflow-y-auto px-4 py-6"
      >
        {query.isPending && (
          <div role="status" className="flex justify-center gap-2 py-8 text-sm">
            <Loader2Icon className="size-4 animate-spin" />
            {t.workspaceSearch.loadingContext}
          </div>
        )}
        {query.isError && (
          <div role="alert" className="mx-auto max-w-xl py-8 text-sm">
            <p>{t.workspaceSearch.messageUnavailable}</p>
            <Button
              variant="outline"
              className="mt-3"
              onClick={() => void query.refetch()}
            >
              {t.workspaceSearch.retry}
            </Button>
          </div>
        )}
        {data && (
          <div className="mx-auto flex max-w-3xl flex-col gap-6">
            {data.has_before && first && (
              <Button
                variant="ghost"
                onClick={() =>
                  setAnchor({ messageId: first.message_id, seq: first.seq })
                }
              >
                <ArrowUpIcon />
                {t.workspaceSearch.earlier}
              </Button>
            )}
            {data.messages.map((message) => (
              <article
                key={`${message.message_id}:${message.seq}`}
                ref={message.seq === data.target_seq ? target : undefined}
                data-message-id={message.message_id}
                data-search-target={
                  message.seq === data.target_seq || undefined
                }
                className={cn(
                  "rounded-lg p-4 text-sm",
                  message.role === "user" && "bg-muted",
                  message.seq === data.target_seq && "ring-ring ring-2",
                )}
              >
                <div className="text-muted-foreground mb-2 flex items-center gap-3 text-sm">
                  <span>
                    {message.role === "user"
                      ? t.workspaceSearch.user
                      : t.workspaceSearch.assistant}
                  </span>
                  {message.seq === data.target_seq && (
                    <span>{t.workspaceSearch.matchedMessage}</span>
                  )}
                </div>
                {message.role === "assistant" ? (
                  <MarkdownContent
                    content={message.text}
                    isLoading={false}
                    components={markdownComponents}
                  />
                ) : (
                  <div className="break-words whitespace-pre-wrap">
                    {message.text}
                  </div>
                )}
              </article>
            ))}
            {data.has_after && last && (
              <Button
                variant="ghost"
                onClick={() =>
                  setAnchor({ messageId: last.message_id, seq: last.seq })
                }
              >
                <ArrowDownIcon />
                {t.workspaceSearch.later}
              </Button>
            )}
          </div>
        )}
      </div>
    </section>
  );
}
