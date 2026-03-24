import assert from "node:assert/strict";
import test from "node:test";

type RecentChatListActionsModule = {
  openRecentChatInNewWindow: (
    threadId: string,
    options: {
      isDesktop: boolean;
      openThreadInNewWindow?: (threadId: string) => Promise<string | undefined>;
    },
  ) => Promise<string | undefined>;
  shouldShowOpenInNewWindowAction: (options: {
    isDesktop: boolean;
    staticWebsiteOnly: string | undefined;
  }) => boolean;
};

const recentChatListActionsModuleUrl = new URL(
  "./recent-chat-list-actions.ts",
  import.meta.url,
).href;
const { openRecentChatInNewWindow, shouldShowOpenInNewWindowAction } =
  (await import(recentChatListActionsModuleUrl)) as RecentChatListActionsModule;

void test(
  "shouldShowOpenInNewWindowAction returns true in desktop mode",
  () => {
    assert.equal(
      shouldShowOpenInNewWindowAction({
        isDesktop: true,
        staticWebsiteOnly: "false",
      }),
      true,
    );
  },
);

void test("shouldShowOpenInNewWindowAction returns false in web mode", () => {
  assert.equal(
    shouldShowOpenInNewWindowAction({
      isDesktop: false,
      staticWebsiteOnly: "false",
    }),
    false,
  );
});

void test("openRecentChatInNewWindow is a safe no-op outside desktop mode", async () => {
  let invokeCount = 0;

  const result = await openRecentChatInNewWindow("thread-123", {
    isDesktop: false,
    openThreadInNewWindow: async () => {
      invokeCount += 1;
      return "chat-thread-thread-123-1";
    },
  });

  assert.equal(result, undefined);
  assert.equal(invokeCount, 0);
});

void test("openRecentChatInNewWindow calls the bridge in desktop mode", async () => {
  let invokedThreadId = "";

  const result = await openRecentChatInNewWindow("thread-123", {
    isDesktop: true,
    openThreadInNewWindow: async (threadId: string) => {
      invokedThreadId = threadId;
      return "chat-thread-thread-123-1";
    },
  });

  assert.equal(result, "chat-thread-thread-123-1");
  assert.equal(invokedThreadId, "thread-123");
});
