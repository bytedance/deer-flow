"use client";

import { useCallback, useEffect, useState } from "react";

import { type PromptInputMessage } from "@/components/ai-elements/prompt-input";
import { ThreadContext } from "@/components/workspace/messages/context";
import { TableWorkspace } from "@/components/workspace/table";
import { useThreadSettings } from "@/core/settings";
import { ensureTeableAgent } from "@/core/teable/api";
import { useThreadStream } from "@/core/threads/hooks";
import { uuid } from "@/core/utils/uuid";

const AGENT_NAME = "teable-agent";

export default function TablePage() {
  const [threadId, setThreadId] = useState(() => uuid());
  const [isNewThread, setIsNewThread] = useState(true);
  const [settings] = useThreadSettings(threadId);

  useEffect(() => {
    void ensureTeableAgent();
  }, []);

  const [thread, sendMessage] = useThreadStream({
    threadId: isNewThread ? undefined : threadId,
    context: { ...settings.context, agent_name: AGENT_NAME },
    onStart: (createdThreadId) => {
      setThreadId(createdThreadId);
      setIsNewThread(false);
      history.replaceState(null, "", `/workspace/table/${createdThreadId}`);
    },
  });

  const handleSubmit = useCallback(
    (message: PromptInputMessage) => {
      void sendMessage(threadId, message, { agent_name: AGENT_NAME });
    },
    [sendMessage, threadId],
  );

  const handleStop = useCallback(async () => {
    await thread.stop();
  }, [thread]);

  return (
    <ThreadContext.Provider value={{ thread }}>
      <TableWorkspace
        threadId={threadId}
        thread={thread}
        isNewThread={isNewThread}
        onSubmit={handleSubmit}
        onStop={handleStop}
      />
    </ThreadContext.Provider>
  );
}
