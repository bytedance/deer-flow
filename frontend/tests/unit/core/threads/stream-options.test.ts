import { afterEach, expect, test, rs } from "@rstest/core";
import { QueryClient } from "@tanstack/react-query";

import { DEFAULT_THREAD_SEARCH_PARAMS } from "@/core/threads/thread-search-query";
import type { AgentThread } from "@/core/threads/types";

async function captureThreadStreamOptions(
  assistantId?: string,
  {
    hiddenFromThreadLists,
    queryClient,
  }: { hiddenFromThreadLists?: boolean; queryClient?: QueryClient } = {},
) {
  let capturedOptions: Record<string, unknown> | undefined;

  rs.resetModules();
  rs.doMock("react", () => ({
    createContext: () => ({}),
    useContext: () => undefined,
    useCallback: <T extends (...args: never[]) => unknown>(callback: T) =>
      callback,
    useEffect: () => undefined,
    useMemo: <T>(factory: () => T) => factory(),
    useRef: <T>(initialValue: T) => ({ current: initialValue }),
    useState: <T>(initialValue: T | (() => T)) => [
      typeof initialValue === "function"
        ? (initialValue as () => T)()
        : initialValue,
      rs.fn(),
    ],
  }));
  rs.doMock("@tanstack/react-query", () => ({
    useInfiniteQuery: () => ({
      data: { pages: [] },
      error: null,
      fetchNextPage: rs.fn(),
      hasNextPage: false,
      isFetchingNextPage: false,
      isLoading: false,
    }),
    useMutation: rs.fn(),
    useQuery: () => ({
      data: [],
      refetch: rs.fn(),
    }),
    useQueryClient: () =>
      queryClient ?? {
        invalidateQueries: rs.fn(),
        setQueriesData: rs.fn(),
      },
  }));
  rs.doMock("@langchain/langgraph-sdk/react", () => ({
    useStream: (options: Record<string, unknown>) => {
      capturedOptions = options;
      return {
        isLoading: false,
        messages: [],
        stop: rs.fn(),
        submit: rs.fn(),
        values: { title: "", messages: [] },
      };
    },
  }));
  rs.doMock("@/core/api", () => ({
    getAPIClient: () => ({}),
  }));
  rs.doMock("@/core/i18n/hooks", () => ({
    useI18n: () => ({
      t: {
        pages: { newChat: "New chat" },
        uploads: { uploadingFiles: "Uploading files" },
        inputBox: { runInputUnavailable: "The current Run is unavailable" },
      },
    }),
  }));
  rs.doMock("@/core/tasks/context", () => ({
    useSubtaskContext: () => ({
      tasksRef: { current: {} },
      setTasks: rs.fn(),
    }),
    useUpdateSubtask: () => rs.fn(),
  }));

  const { useThreadStream } = await import("@/core/threads/hooks");
  function ThreadStreamCapture() {
    useThreadStream({
      context: {
        mode: "flash",
      },
      assistantId,
      isMock: true,
      hiddenFromThreadLists,
    } as never);
    return null;
  }
  ThreadStreamCapture();

  return capturedOptions;
}

afterEach(() => {
  rs.doUnmock("react");
  rs.doUnmock("@tanstack/react-query");
  rs.doUnmock("@langchain/langgraph-sdk/react");
  rs.doUnmock("@/core/api");
  rs.doUnmock("@/core/i18n/hooks");
  rs.doUnmock("@/core/tasks/context");
  rs.resetModules();
});

test("does not subscribe to unsupported LangGraph events mode", async () => {
  const options = await captureThreadStreamOptions();

  expect(options).toBeDefined();
  expect(options).not.toHaveProperty("onLangChainEvent");
  expect(options).toHaveProperty("onUpdateEvent");
  expect(options).toHaveProperty("onCustomEvent");
});

test("forwards the custom-agent assistant identity to the stream", async () => {
  const options = await captureThreadStreamOptions("researcher");

  expect(options).toHaveProperty("assistantId", "researcher");
});

// The @ mention picker reads the unfiltered infinite list and the reference
// picker the default search; both drop side chats only when they fetch.
const MENTION_PICKER_KEY = [
  "threads",
  "searchInfinite",
  {
    sortBy: "updated_at",
    sortOrder: "desc",
    select: ["thread_id", "updated_at", "values", "metadata"],
  },
];
const REFERENCE_PICKER_KEY = [
  "threads",
  "search",
  DEFAULT_THREAD_SEARCH_PARAMS,
];

async function pickerThreadIdsAfterRunCreated(hiddenFromThreadLists: boolean) {
  const queryClient = new QueryClient();
  const existing = {
    thread_id: "main-thread",
    values: { title: "Main chat" },
    metadata: {},
  } as unknown as AgentThread;
  queryClient.setQueryData(MENTION_PICKER_KEY, {
    // The fetch already dropped the side chat.
    pages: [{ threads: [existing], hiddenCount: 1, hasMore: false }],
    pageParams: [0],
  });
  queryClient.setQueryData(REFERENCE_PICKER_KEY, [existing]);
  const options = await captureThreadStreamOptions(undefined, {
    hiddenFromThreadLists,
    queryClient,
  });

  (options?.onCreated as (meta: { thread_id: string; run_id: string }) => void)(
    { thread_id: "run-thread", run_id: "run-1" },
  );

  const mention = queryClient.getQueryData<{
    pages: { threads: AgentThread[] }[];
  }>(MENTION_PICKER_KEY);
  const reference =
    queryClient.getQueryData<AgentThread[]>(REFERENCE_PICKER_KEY);
  queryClient.clear();
  return {
    mention: mention?.pages.flatMap((page) =>
      page.threads.map((thread) => thread.thread_id),
    ),
    reference: reference?.map((thread) => thread.thread_id),
  };
}

test("a run of a chat hidden from thread lists leaves the picker caches alone", async () => {
  expect(await pickerThreadIdsAfterRunCreated(true)).toEqual({
    mention: ["main-thread"],
    reference: ["main-thread"],
  });
});

test("a new chat's run still shows in the picker caches right away", async () => {
  expect(await pickerThreadIdsAfterRunCreated(false)).toEqual({
    mention: ["run-thread", "main-thread"],
    reference: ["run-thread", "main-thread"],
  });
});
