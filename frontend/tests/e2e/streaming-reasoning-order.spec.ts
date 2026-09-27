import { createServer } from "node:http";
import type { AddressInfo } from "node:net";

import { expect, test, type Locator } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

const STREAMING_THREAD_ID = "00000000-0000-0000-0000-000000004576";
const SETTLED_THREAD_ID = "00000000-0000-0000-0000-000000004577";
const RUN_ID = "00000000-0000-0000-0000-000000004578";

const REASONING_TEXT =
  "The user asked who I am, so I will list the core capabilities.";
const ANSWER_TEXT = "I am DeerFlow, an open-source super agent.";

for (const literal of ["<think>sample reasoning</think>", "<think>"]) {
  test(`preserves literal code ${literal} and its following explanation`, async ({
    page,
  }, testInfo) => {
    mockLangGraphAPI(page, {
      threads: [
        {
          thread_id: SETTLED_THREAD_ID,
          title: "Literal reasoning tags in code",
          messages: [
            {
              type: "human",
              id: "literal-human",
              content: "Show a reasoning-tag example.",
            },
            {
              type: "ai",
              id: "literal-ai",
              content: `Example:\n\n\`\`\`xml\n${literal}\n\`\`\`\n\nThis is literal code, not model reasoning.`,
            },
          ],
        },
      ],
    });
    await page.goto(`/workspace/chats/${SETTLED_THREAD_ID}`);
    await expect(
      page.locator("pre").filter({ hasText: literal }),
    ).toBeVisible();
    await expect(
      page.getByText("This is literal code, not model reasoning."),
    ).toBeVisible();
    await expect(page.getByText("Reasoning", { exact: true })).toHaveCount(0);
    await page.screenshot({
      path: testInfo.outputPath("literal-think-code.png"),
    });
  });
}

const INITIAL_MESSAGES = [
  {
    type: "human",
    id: "msg-human-4576",
    content: [{ type: "text", text: "Who are you?" }],
  },
];

for (const [opener, indent] of [
  ["- ~~~xml", "  "],
  ["10. ```xml", "    "],
]) {
  test(`separates literal and real reasoning after a list fence: ${opener}`, async ({
    page,
  }, testInfo) => {
    const closer = opener!.includes("~~~") ? "~~~" : "```";
    mockLangGraphAPI(page, {
      threads: [
        {
          thread_id: SETTLED_THREAD_ID,
          title: "List-contained reasoning example",
          messages: [
            ...INITIAL_MESSAGES,
            {
              type: "ai",
              id: "list-fence-ai",
              content: `${opener}\n${indent}<think>literal example</think>\n${indent}${closer}\n\n<think>Actual model reasoning.</think>Visible answer after the list.`,
            },
          ],
        },
      ],
    });
    await page.goto(`/workspace/chats/${SETTLED_THREAD_ID}`);
    await expect(
      page
        .locator("li pre")
        .filter({ hasText: "<think>literal example</think>" }),
    ).toBeVisible();
    await expect(page.getByText("Reasoning", { exact: true })).toBeVisible();
    await expect(
      page.getByText("Visible answer after the list.", { exact: true }),
    ).toBeVisible();
    await expect(
      page.getByText("<think>Actual model reasoning.</think>", {
        exact: false,
      }),
    ).toHaveCount(0);
    await page.screenshot({
      path: testInfo.outputPath("list-fence-reasoning.png"),
    });
  });
}

for (const block of ["# Result", "- Result", "```sh\necho hi\n```"]) {
  test(`extracts reasoning after a block interrupts inline code: ${block}`, async ({
    page,
  }) => {
    mockLangGraphAPI(page, {
      threads: [
        {
          thread_id: SETTLED_THREAD_ID,
          title: "Reasoning at a block boundary",
          messages: [
            ...INITIAL_MESSAGES,
            {
              type: "ai",
              id: "block-boundary-ai",
              content: `Run \`this command\n${block}\n<think>Internal boundary reasoning.</think>Visible final answer.`,
            },
          ],
        },
      ],
    });
    await page.goto(`/workspace/chats/${SETTLED_THREAD_ID}`);
    await expect(page.getByText("Reasoning", { exact: true })).toBeVisible();
    await expect(
      page.getByText("Visible final answer.", { exact: false }),
    ).toBeVisible();
    await expect(
      page.getByText("<think>Internal boundary reasoning.</think>", {
        exact: false,
      }),
    ).toHaveCount(0);
  });
}

test("preserves inline code after the first backtick is escaped", async ({
  page,
}) => {
  mockLangGraphAPI(page, {
    threads: [
      {
        thread_id: SETTLED_THREAD_ID,
        title: "Escaped backtick run",
        messages: [
          ...INITIAL_MESSAGES,
          {
            type: "ai",
            id: "escaped-backtick-ai",
            content: "Use \\``<think>sample</think>` literally.",
          },
        ],
      },
    ],
  });
  await page.goto(`/workspace/chats/${SETTLED_THREAD_ID}`);
  await expect(
    page.locator("code").filter({ hasText: "<think>sample</think>" }),
  ).toBeVisible();
  await expect(page.getByText("Reasoning", { exact: true })).toHaveCount(0);
});

const SETTLED_AI_MESSAGE = {
  type: "ai",
  id: "msg-ai-4576-settled",
  content: ANSWER_TEXT,
  additional_kwargs: { reasoning_content: REASONING_TEXT },
};

/**
 * One AI chunk carrying both reasoning and answer text, which is the state the
 * bubble is in while a reasoning model streams its answer.
 */
function reasoningStreamFrames() {
  const events = [
    {
      event: "metadata",
      data: { run_id: RUN_ID, thread_id: STREAMING_THREAD_ID },
    },
    {
      event: "values",
      data: {
        messages: [
          ...INITIAL_MESSAGES,
          {
            type: "human",
            id: "msg-human-4576-follow-up",
            content: [{ type: "text", text: "Summarize that briefly" }],
          },
        ],
      },
    },
    {
      event: "messages",
      data: [
        {
          content: ANSWER_TEXT,
          additional_kwargs: { reasoning_content: REASONING_TEXT },
          response_metadata: {},
          type: "AIMessageChunk",
          name: null,
          id: "msg-ai-4576-streaming",
          tool_calls: [],
          invalid_tool_calls: [],
          usage_metadata: null,
          tool_call_chunks: [],
          chunk_position: null,
        },
        {},
      ],
    },
  ];

  return events.map(
    (event) => `event: ${event.event}\ndata: ${JSON.stringify(event.data)}\n\n`,
  );
}

/** Holds the SSE connection open so the turn stays in its streaming state. */
async function startHeldOpenStreamServer() {
  const frames = reasoningStreamFrames();
  const server = createServer((_request, response) => {
    response.writeHead(200, {
      "Access-Control-Allow-Origin": "*",
      "Cache-Control": "no-cache",
      "Content-Type": "text/event-stream",
    });
    response.write(frames.join(""));
  });

  await new Promise<void>((resolve, reject) => {
    const handleError = (error: Error) => reject(error);
    server.once("error", handleError);
    server.listen(0, "127.0.0.1", () => {
      server.off("error", handleError);
      resolve();
    });
  });

  const { port } = server.address() as AddressInfo;
  return {
    url: `http://127.0.0.1:${port}/runs/stream`,
    async close() {
      server.closeAllConnections();
      await new Promise<void>((resolve, reject) => {
        server.close((error) => (error ? reject(error) : resolve()));
      });
    },
  };
}

async function expectRenderedAbove(upper: Locator, lower: Locator) {
  await expect(upper).toBeVisible();
  await expect(lower).toBeVisible();
  const upperBox = await upper.boundingBox();
  const lowerBox = await lower.boundingBox();
  expect(upperBox).not.toBeNull();
  expect(lowerBox).not.toBeNull();
  expect(upperBox!.y).toBeLessThan(lowerBox!.y);
}

test("renders reasoning above the answer text while the turn is streaming", async ({
  page,
}) => {
  const streamServer = await startHeldOpenStreamServer();
  mockLangGraphAPI(page, {
    threads: [
      {
        thread_id: STREAMING_THREAD_ID,
        title: "Streaming reasoning order",
        messages: INITIAL_MESSAGES,
      },
    ],
  });
  await page.route("**/api/langgraph/threads/*/runs/stream", (route) =>
    route.continue({ url: streamServer.url }),
  );

  try {
    await page.goto(`/workspace/chats/${STREAMING_THREAD_ID}`);

    const textarea = page.getByPlaceholder(/how can i assist you/i);
    await expect(textarea).toBeVisible({ timeout: 15_000 });
    await textarea.fill("Summarize that briefly");
    await textarea.press("Enter");

    // The streaming turn renders inside the assistant bubble, whose
    // reasoning disclosure is labelled "Reasoning".
    await expectRenderedAbove(
      page.getByText("Reasoning", { exact: true }),
      page.getByText(ANSWER_TEXT),
    );
  } finally {
    await streamServer.close();
  }
});

test("renders reasoning above the answer text after the turn settles", async ({
  page,
}) => {
  mockLangGraphAPI(page, {
    threads: [
      {
        thread_id: SETTLED_THREAD_ID,
        title: "Settled reasoning order",
        messages: [...INITIAL_MESSAGES, SETTLED_AI_MESSAGE],
      },
    ],
  });

  await page.goto(`/workspace/chats/${SETTLED_THREAD_ID}`);

  // The settled turn renders as an assistant bubble, whose reasoning
  // disclosure is labelled "Reasoning".
  await expectRenderedAbove(
    page.getByText("Reasoning", { exact: true }),
    page.getByText(ANSWER_TEXT),
  );
});
