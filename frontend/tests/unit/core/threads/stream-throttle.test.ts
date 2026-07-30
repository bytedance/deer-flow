import { expect, rs, test } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { I18nContext } from "@/core/i18n/context";
import { DEFAULT_LOCAL_SETTINGS } from "@/core/settings/local";

const streamMockState = rs.hoisted(() => ({
  options: undefined as { throttle?: boolean | number } | undefined,
}));

rs.mock("@langchain/langgraph-sdk/react", () => ({
  useStream: (options: { throttle?: boolean | number }) => {
    streamMockState.options = options;
    return {
      isLoading: false,
      messages: [],
      stop: async () => undefined,
      submit: async () => undefined,
      values: {
        artifacts: [],
        messages: [],
        title: "",
        todos: [],
      },
    };
  },
}));

test("batches stream subscription updates in a macrotask", async () => {
  const { useThreadStream } = await import("@/core/threads/hooks");
  const queryClient = new QueryClient();

  function StreamProbe() {
    useThreadStream({
      context: DEFAULT_LOCAL_SETTINGS.context,
      isMock: true,
      threadId: "thread-1",
    });
    return null;
  }

  renderToStaticMarkup(
    createElement(
      QueryClientProvider,
      { client: queryClient },
      createElement(
        I18nContext.Provider,
        {
          value: {
            locale: "en-US",
            setLocale: () => undefined,
          },
        },
        createElement(StreamProbe),
      ),
    ),
  );

  expect(streamMockState.options?.throttle).toBe(true);
});
