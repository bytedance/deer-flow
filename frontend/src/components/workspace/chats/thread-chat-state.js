export function reduceThreadChatState(current, input) {
  if (current.persistedThreadId && input.threadIdFromPath === "new") {
    return current;
  }

  if (input.pathname.endsWith("/new")) {
    if (current.persistedThreadId == null) {
      return current;
    }

    return {
      threadId: input.nextDraftThreadId,
      persistedThreadId: null,
    };
  }

  if (input.threadIdFromPath === "new") {
    return current;
  }

  return {
    threadId: input.threadIdFromPath,
    persistedThreadId: input.threadIdFromPath,
  };
}

export function shouldShowNewThreadLayout({ isNewThread, messageCount }) {
  return isNewThread && messageCount === 0;
}
