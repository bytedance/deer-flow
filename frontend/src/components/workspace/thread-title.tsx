import type { BaseStream } from "@langchain/langgraph-sdk";
import { useEffect } from "react";

import { useI18n } from "@/core/i18n/hooks";
import type { AgentThreadState } from "@/core/threads";

import { useThreadChat } from "./chats";
import { FlipDisplay } from "./flip-display";

export type ThreadTitleProps = {
  className?: string;
  threadId: string;
  thread: BaseStream<AgentThreadState>;
  canonicalTitle?: string;
};

export function ThreadTitle({
  threadId,
  thread,
  canonicalTitle,
}: ThreadTitleProps) {
  const { t } = useI18n();
  const { isNewThread } = useThreadChat();
  const title = canonicalTitle?.length ? canonicalTitle : thread.values?.title;

  useEffect(() => {
    let _title = t.pages.untitled;

    if (title) {
      _title = title;
    } else if (isNewThread) {
      _title = t.pages.newChat;
    }
    if (thread.isThreadLoading) {
      document.title = `Loading... - ${t.pages.appName}`;
    } else {
      document.title = `${_title} - ${t.pages.appName}`;
    }
  }, [
    isNewThread,
    t.pages.newChat,
    t.pages.untitled,
    t.pages.appName,
    thread.isThreadLoading,
    title,
  ]);

  if (!title) {
    return null;
  }
  return <FlipDisplay uniqueKey={threadId}>{title}</FlipDisplay>;
}
