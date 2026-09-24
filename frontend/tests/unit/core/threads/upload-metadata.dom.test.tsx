import type { Message } from "@langchain/langgraph-sdk";
import { expect, rs, test } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import { createElement, type ReactNode } from "react";

import { I18nContext } from "@/core/i18n/context";
import { enUS } from "@/core/i18n/locales/en-US";
import { DEFAULT_LOCAL_SETTINGS } from "@/core/settings/local";

const mocks = rs.hoisted(() => ({
  values: { messages: [] as Message[], artifacts: [], title: "", todos: [] },
  submit: rs.fn(async (_input: { messages: Message[] }) => undefined),
}));

rs.mock("@langchain/langgraph-sdk/react", () => ({
  useStream: () => ({
    isLoading: false,
    messages: mocks.values.messages,
    stop: async () => undefined,
    submit: mocks.submit,
    values: mocks.values,
  }),
}));

rs.mock("@/core/uploads", () => ({
  promptInputFilePartToFile: async () => new File(["pdf"], "report.pdf"),
  uploadFiles: async () => ({
    files: [
      {
        filename: "report.pdf",
        size: 3,
        virtual_path: "/mnt/user-data/uploads/report.pdf",
        markdown_file: "report_1.md",
      },
    ],
  }),
}));

test("preserves the upload response's exact Markdown companion in submitted and optimistic metadata", async () => {
  const { useThreadStream } = await import("@/core/threads/hooks");
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) =>
    createElement(
      QueryClientProvider,
      { client: queryClient },
      createElement(
        I18nContext.Provider,
        {
          value: { locale: "en-US", setLocale: () => undefined, t: enUS },
        },
        children,
      ),
    );
  const { result, unmount } = renderHook(
    () =>
      useThreadStream({
        context: DEFAULT_LOCAL_SETTINGS.context,
        isMock: true,
        threadId: "thread-1",
      }),
    { wrapper },
  );

  try {
    await act(async () => {
      await result.current.sendMessage("thread-1", {
        text: "Read this PDF",
        files: [
          {
            type: "file",
            filename: "report.pdf",
            mediaType: "application/pdf",
            url: "data:application/pdf;base64,cGRm",
          },
        ],
      });
    });

    const expectedFiles = [
      {
        filename: "report.pdf",
        size: 3,
        path: "/mnt/user-data/uploads/report.pdf",
        status: "uploaded",
        markdown_file: "report_1.md",
      },
    ];
    expect(
      mocks.submit.mock.calls[0]?.[0].messages.at(-1)?.additional_kwargs?.files,
    ).toEqual(expectedFiles);
    expect(
      result.current.thread.messages.find((message) => message.type === "human")
        ?.additional_kwargs?.files,
    ).toEqual(expectedFiles);
  } finally {
    unmount();
    queryClient.clear();
  }
});
