import { createServer, type ServerResponse } from "node:http";
import type { AddressInfo } from "node:net";

import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

const THREAD_ID = "00000000-0000-0000-0000-000000007332";
const RUN_ID = "00000000-0000-0000-0000-000000007335";
const QUESTION = "Continue with the attached report";
const ANSWER = "Working on the new request";

// Keep the HTTP response open until the assertions have observed each frame.
// This exercises the real SDK and chat page, without a model or live Gateway.
async function controlledStream() {
  let response: ServerResponse | undefined;
  let connected!: () => void;
  const started = new Promise<void>((resolve) => {
    connected = resolve;
  });
  const server = createServer((_request, res) => {
    response = res;
    res.writeHead(200, {
      "Access-Control-Allow-Origin": "*",
      "Cache-Control": "no-cache",
      "Content-Type": "text/event-stream",
    });
    res.write(
      `event: metadata\ndata: ${JSON.stringify({ run_id: RUN_ID, thread_id: THREAD_ID })}\n\n`,
    );
    connected();
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  return {
    url: `http://127.0.0.1:${(server.address() as AddressInfo).port}/runs/stream`,
    started,
    send(event: string, data: unknown) {
      if (!response) throw new Error("Stream has not connected");
      response.write(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);
    },
    async close() {
      response?.end();
      server.closeAllConnections();
      await new Promise<void>((resolve, reject) =>
        server.close((error) => (error ? reject(error) : resolve())),
      );
    },
  };
}

for (const withFile of [false, true]) {
  test(`keeps the human visible through incremental handoff${withFile ? " after upload completes" : ""}`, async ({
    page,
  }) => {
    const stream = await controlledStream();
    mockLangGraphAPI(page, {
      threads: [
        {
          thread_id: THREAD_ID,
          title: "Handoff regression",
          messages: [
            { type: "human", id: "old-question", content: "Previous question" },
            { type: "ai", id: "old-answer", content: "Previous answer" },
          ],
        },
      ],
    });
    let submittedHuman: Record<string, unknown> | undefined;
    await page.route(
      "**/api/langgraph/threads/*/runs/stream",
      async (route) => {
        const body = route.request().postDataJSON() as {
          input: { messages: Array<Record<string, unknown>> };
          stream_mode: string[];
        };
        // Production deliberately omits values frames. A fabricated sequence on
        // the incremental echo would hide the upload-status regression.
        expect(body.stream_mode).not.toContain("values");
        submittedHuman = body.input.messages.find(
          (message) => message.type === "human",
        );
        await route.continue({ url: stream.url });
      },
    );
    let releaseUpload!: () => void;
    const uploadReady = new Promise<void>((resolve) => {
      releaseUpload = resolve;
    });
    await page.route("**/api/threads/*/uploads", async (route) => {
      await uploadReady;
      await route.fulfill({
        json: {
          success: true,
          message: "Uploaded",
          skipped_files: [],
          files: [
            {
              filename: "report.txt",
              size: 6,
              path: "report.txt",
              virtual_path: "/mnt/user-data/uploads/report.txt",
              artifact_url: `/api/threads/${THREAD_ID}/uploads/report.txt`,
            },
          ],
        },
      });
    });
    try {
      await page.goto(`/workspace/chats/${THREAD_ID}`);
      const input = page.getByPlaceholder(/how can i assist you/i);
      await expect(input).toBeVisible();
      if (withFile) {
        await page.getByLabel("Upload files").setInputFiles({
          name: "report.txt",
          mimeType: "text/plain",
          buffer: Buffer.from("Report"),
        });
      }
      await input.fill(QUESTION);
      await input.press("Enter");
      if (withFile) {
        await expect(
          page.getByText("Uploading files, please wait...", { exact: true }),
        ).toBeVisible();
      }
      releaseUpload();
      await stream.started;
      expect(submittedHuman).toBeDefined();
      // TodoMiddleware emits this hidden HumanMessage through the incremental
      // stream. It must not count as confirmation of the submitted question.
      stream.send("messages", [
        {
          type: "human",
          id: "todo-control",
          name: "todo_reminder",
          content: "Keep track of the task",
          additional_kwargs: { hide_from_ui: true },
        },
        { langgraph_node: "TodoMiddleware.before_model" },
      ]);
      stream.send("messages", [
        {
          type: "ai",
          id: "new-answer",
          content: ANSWER,
        },
        { langgraph_node: "agent", langgraph_step: 1 },
      ]);
      await expect(page.getByText(ANSWER, { exact: true })).toBeVisible();
      await expect(page.getByText(QUESTION, { exact: true })).toBeVisible();
      await expect(
        page.getByText("Keep track of the task", { exact: true }),
      ).toBeHidden();
      await expect(
        page.getByText("Uploading files, please wait...", { exact: true }),
      ).toBeHidden();
      // The normal unpositioned echo arrives while the response remains open.
      stream.send("messages", [
        {
          ...submittedHuman,
          id: `${String(submittedHuman?.id)}__user`,
        },
        { langgraph_node: "DynamicContextMiddleware.before_model" },
      ]);
      stream.send("messages", [
        {
          type: "ai",
          id: "echo-observed",
          content: "The input echo has arrived",
        },
        { langgraph_node: "agent", langgraph_step: 2 },
      ]);
      await expect(
        page.getByText("The input echo has arrived", { exact: true }),
      ).toBeVisible();
      await expect(page.getByText(QUESTION, { exact: true })).toHaveCount(1);
      await expect(
        page.getByText("Uploading files, please wait...", { exact: true }),
      ).toBeHidden();
      const ordered = await page
        .getByText(QUESTION, { exact: true })
        .evaluate((human, answer) => {
          const nodes = Array.from(document.querySelectorAll("p"));
          const ai = nodes.find((node) => node.textContent === answer);
          return (
            !!ai &&
            !!(
              human.compareDocumentPosition(ai) &
              Node.DOCUMENT_POSITION_FOLLOWING
            )
          );
        }, ANSWER);
      expect(ordered).toBe(true);
    } finally {
      releaseUpload();
      await stream.close();
    }
  });
}
