import assert from "node:assert/strict";
import test from "node:test";

type ShortcutModule = {
  executeGlobalShortcutAction: (
    shortcut: {
      key: string;
      meta: boolean;
      shift?: boolean;
      action: () => void;
    },
    options?: {
      isDesktop?: () => boolean;
      openNewChatWindow?: () => Promise<string | undefined>;
    },
  ) => void | Promise<string | undefined>;
};

const shortcutModuleUrl = new URL("./use-global-shortcuts.ts", import.meta.url)
  .href;
const { executeGlobalShortcutAction } = (await import(
  shortcutModuleUrl
)) as ShortcutModule;

void test(
  "executeGlobalShortcutAction keeps the new-chat shortcut on the existing web action outside desktop mode",
  async () => {
    let actionCalls = 0;
    let newWindowCalls = 0;

    const result = await executeGlobalShortcutAction(
      {
        key: "n",
        meta: true,
        shift: true,
        action: () => {
          actionCalls += 1;
        },
      },
      {
        isDesktop: () => false,
        openNewChatWindow: async () => {
          newWindowCalls += 1;
          return "chat-new-1";
        },
      },
    );

    assert.equal(result, undefined);
    assert.equal(actionCalls, 1);
    assert.equal(newWindowCalls, 0);
  },
);

void test(
  "executeGlobalShortcutAction routes the new-chat shortcut to a new desktop window",
  async () => {
    let actionCalls = 0;
    let newWindowCalls = 0;

    const result = await executeGlobalShortcutAction(
      {
        key: "n",
        meta: true,
        shift: true,
        action: () => {
          actionCalls += 1;
        },
      },
      {
        isDesktop: () => true,
        openNewChatWindow: async () => {
          newWindowCalls += 1;
          return "chat-new-1";
        },
      },
    );

    assert.equal(result, "chat-new-1");
    assert.equal(actionCalls, 0);
    assert.equal(newWindowCalls, 1);
  },
);

void test(
  "executeGlobalShortcutAction leaves unrelated shortcuts unchanged in desktop mode",
  async () => {
    let actionCalls = 0;
    let newWindowCalls = 0;

    const result = await executeGlobalShortcutAction(
      {
        key: ",",
        meta: true,
        action: () => {
          actionCalls += 1;
        },
      },
      {
        isDesktop: () => true,
        openNewChatWindow: async () => {
          newWindowCalls += 1;
          return "chat-new-1";
        },
      },
    );

    assert.equal(result, undefined);
    assert.equal(actionCalls, 1);
    assert.equal(newWindowCalls, 0);
  },
);
