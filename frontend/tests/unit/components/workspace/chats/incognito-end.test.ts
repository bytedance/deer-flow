import { describe, expect, test } from "@rstest/core";

import { shouldRequestIncognitoEnd } from "@/components/workspace/chats/incognito-end";

describe("shouldRequestIncognitoEnd", () => {
  test("ends a materialized thread", () => {
    expect(
      shouldRequestIncognitoEnd({
        isNewThread: false,
        isMock: false,
        threadId: "thread-1",
        createdThreadId: null,
      }),
    ).toBe(true);
  });

  test("ends a pre-created row while the URL still calls the chat new", () => {
    expect(
      shouldRequestIncognitoEnd({
        isNewThread: true,
        isMock: false,
        threadId: "thread-1",
        createdThreadId: "thread-1",
      }),
    ).toBe(true);
  });

  test("skips a lazy chat that never reached the server", () => {
    expect(
      shouldRequestIncognitoEnd({
        isNewThread: true,
        isMock: false,
        threadId: "thread-1",
        createdThreadId: null,
      }),
    ).toBe(false);
  });

  test("ignores a row created for a different thread id", () => {
    expect(
      shouldRequestIncognitoEnd({
        isNewThread: true,
        isMock: false,
        threadId: "thread-2",
        createdThreadId: "thread-1",
      }),
    ).toBe(false);
  });

  test("never calls the Gateway in mock mode", () => {
    expect(
      shouldRequestIncognitoEnd({
        isNewThread: false,
        isMock: true,
        threadId: "thread-1",
        createdThreadId: "thread-1",
      }),
    ).toBe(false);
  });
});