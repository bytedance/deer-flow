import type { AIMessage, Message, ToolMessage } from "@langchain/langgraph-sdk";
import {
  afterEach,
  beforeEach,
  describe,
  expect,
  test,
  rs,
} from "@rstest/core";

const ENV_KEYS = [
  "NEXT_PUBLIC_BACKEND_BASE_URL",
  "NEXT_PUBLIC_STATIC_WEBSITE_ONLY",
] as const;

type EnvSnapshot = Partial<
  Record<(typeof ENV_KEYS)[number], string | undefined>
>;

function snapshotEnv(): EnvSnapshot {
  const snapshot: EnvSnapshot = {};
  for (const key of ENV_KEYS) {
    snapshot[key] = process.env[key];
  }
  return snapshot;
}

function setEnv(key: (typeof ENV_KEYS)[number], value: string | undefined) {
  const env = process.env as Record<string, string | undefined>;
  if (value === undefined) {
    delete env[key];
  } else {
    env[key] = value;
  }
}

function restoreEnv(snapshot: EnvSnapshot) {
  for (const key of ENV_KEYS) {
    setEnv(key, snapshot[key]);
  }
}

async function loadFreshArtifactUtils() {
  rs.resetModules();
  return await import("@/core/artifacts/utils");
}

describe("artifact URL helpers", () => {
  let saved: EnvSnapshot;

  beforeEach(() => {
    saved = snapshotEnv();
    setEnv("NEXT_PUBLIC_BACKEND_BASE_URL", undefined);
    setEnv("NEXT_PUBLIC_STATIC_WEBSITE_ONLY", undefined);
  });

  afterEach(() => {
    restoreEnv(saved);
  });

  describe("Markdown artifact image destinations", () => {
    const context = {
      filepath: "/mnt/user-data/outputs/reports/report.md",
      threadId: "thread/1",
    };

    test.each([
      ["chart.png", "/mnt/user-data/outputs/reports/chart.png"],
      ["./charts/a.png", "/mnt/user-data/outputs/reports/charts/a.png"],
      ["../chart.png", "/mnt/user-data/outputs/chart.png"],
      ["%2e%2e/chart.png", "/mnt/user-data/outputs/chart.png"],
      ["/mnt/user-data/uploads/chart.png", "/mnt/user-data/uploads/chart.png"],
      ["chart%20one.png", "/mnt/user-data/outputs/reports/chart%20one.png"],
      ["chart%2520one.png", "/mnt/user-data/outputs/reports/chart%2520one.png"],
      [
        "chart%23%3F.png?v=2#crop",
        "/mnt/user-data/outputs/reports/chart%23%3F.png?v=2#crop",
      ],
      ["chart%.png", "/mnt/user-data/outputs/reports/chart%25.png"],
      ["%E5%9B%BE.png", "/mnt/user-data/outputs/reports/%E5%9B%BE.png"],
    ])("resolves %s against the report directory", async (src, path) => {
      const { resolveArtifactImageURL } = await loadFreshArtifactUtils();
      expect(resolveArtifactImageURL(src, context)).toBe(
        `/api/threads/thread%2F1/artifacts${path}`,
      );
    });

    test.each([
      "https://example.com/chart.png",
      "//example.com/chart.png",
      "data:image/png;base64,abc",
      "blob:https://example.com/123",
      "javascript:alert(1)",
      "/api/other.png",
      "",
      "#chart",
      "?v=2",
      "../../../../api/secret.png",
      "%2F%2Fexample.com/chart.png",
      "..%5Cchart.png",
      "\ud800.png",
    ])("does not remap %s into the artifact route", async (src) => {
      const { resolveArtifactImageURL } = await loadFreshArtifactUtils();
      expect(resolveArtifactImageURL(src, context)).toBe(src);
    });

    test("preserves raw percent sequences in the report directory", async () => {
      const { resolveArtifactImageURL } = await loadFreshArtifactUtils();
      expect(
        resolveArtifactImageURL("chart.png", {
          ...context,
          filepath: "/mnt/user-data/outputs/report%20folder/report.md",
        }),
      ).toBe(
        "/api/threads/thread%2F1/artifacts/mnt/user-data/outputs/report%2520folder/chart.png",
      );
    });

    test("uses the configured backend and mock route", async () => {
      setEnv("NEXT_PUBLIC_BACKEND_BASE_URL", "https://backend.example/root");
      const { resolveArtifactImageURL } = await loadFreshArtifactUtils();
      expect(
        resolveArtifactImageURL("chart.png", { ...context, isMock: true }),
      ).toBe(
        "https://backend.example/root/mock/api/threads/thread%2F1/artifacts/mnt/user-data/outputs/reports/chart.png",
      );
    });

    test("uses bundled demo paths in static mode", async () => {
      setEnv("NEXT_PUBLIC_STATIC_WEBSITE_ONLY", "true");
      const { resolveArtifactImageURL } = await loadFreshArtifactUtils();
      expect(resolveArtifactImageURL("../chart.png", context)).toBe(
        "/demo/threads/thread%2F1/user-data/outputs/chart.png",
      );
    });

    test("bases skill previews on their embedded SKILL.md", async () => {
      const { resolveArtifactImageURL } = await loadFreshArtifactUtils();
      expect(
        resolveArtifactImageURL("images/chart.png", {
          ...context,
          filepath: "/mnt/user-data/outputs/example.skill",
        }),
      ).toBe(
        "/api/threads/thread%2F1/artifacts/mnt/user-data/outputs/example.skill/images/chart.png",
      );
    });

    test("does not invent a virtual path for a non-artifact document", async () => {
      const { resolveArtifactImageURL } = await loadFreshArtifactUtils();
      expect(
        resolveArtifactImageURL("chart.png", {
          ...context,
          filepath: "report.md",
        }),
      ).toBe("chart.png");
    });
  });

  test("maps static demo artifact paths to bundled public files", async () => {
    setEnv("NEXT_PUBLIC_STATIC_WEBSITE_ONLY", "true");

    const { resolveArtifactURL, urlOfArtifact } =
      await loadFreshArtifactUtils();

    expect(
      urlOfArtifact({
        filepath: "/mnt/user-data/outputs/index.html",
        threadId: "thread-1",
      }),
    ).toBe("/demo/threads/thread-1/user-data/outputs/index.html");
    expect(
      resolveArtifactURL("/mnt/user-data/outputs/style.css", "thread-1"),
    ).toBe("/demo/threads/thread-1/user-data/outputs/style.css");
  });

  test("encodes reserved characters in artifact URL path segments", async () => {
    const { resolveArtifactURL, urlOfArtifact } =
      await loadFreshArtifactUtils();

    expect(
      urlOfArtifact({
        filepath: "/mnt/user-data/outputs/a#b?.txt",
        threadId: "thread #1",
        download: true,
      }),
    ).toBe(
      "/api/threads/thread%20%231/artifacts/mnt/user-data/outputs/a%23b%3F.txt?download=true",
    );
    expect(
      urlOfArtifact({
        filepath: "/mnt/user-data/outputs/a#b?.txt",
        threadId: "thread #1",
        isMock: true,
      }),
    ).toBe(
      "/mock/api/threads/thread%20%231/artifacts/mnt/user-data/outputs/a%23b%3F.txt",
    );
    expect(
      resolveArtifactURL("/mnt/user-data/outputs/中 文#?.png", "thread #1"),
    ).toBe(
      "/api/threads/thread%20%231/artifacts/mnt/user-data/outputs/%E4%B8%AD%20%E6%96%87%23%3F.png",
    );
    expect(
      resolveArtifactURL("/mnt/user-data/outputs/a%23b%3F.txt", "thread-1"),
    ).toBe(
      "/api/threads/thread-1/artifacts/mnt/user-data/outputs/a%2523b%253F.txt",
    );
  });

  test.each(["report%20final.md", "a%2Fb.txt", "a%2520b.png"])(
    "preserves literal percent escapes in the raw artifact path %s",
    async (filename) => {
      const { resolveArtifactURL, urlOfArtifact } =
        await loadFreshArtifactUtils();
      const filepath = `/mnt/user-data/outputs/${filename}`;
      for (const url of [
        urlOfArtifact({ filepath, threadId: "thread-1" }),
        urlOfArtifact({ filepath, threadId: "thread-1", download: true }),
        urlOfArtifact({ filepath, threadId: "thread-1", isMock: true }),
        resolveArtifactURL(filepath, "thread-1"),
      ]) {
        const pathname = new URL(url, "http://localhost").pathname;
        expect(decodeURIComponent(pathname.split("/artifacts")[1]!)).toBe(
          filepath,
        );
      }
    },
  );

  test("decodes Markdown URLs once before resolving the raw artifact path", async () => {
    const { resolveMarkdownArtifactURL, resolveMessageImageURL } =
      await loadFreshArtifactUtils();
    const rawPath = "/mnt/user-data/outputs/report%20final.png";
    const expected =
      "/api/threads/thread-1/artifacts/mnt/user-data/outputs/report%2520final.png?v=2#detail";

    expect(
      resolveMarkdownArtifactURL(
        "/mnt/user-data/outputs/report%2520final.png?v=2#detail",
        "thread-1",
      ),
    ).toBe(expected);
    expect(
      resolveMessageImageURL("report%2520final.png?v=2#detail", "thread-1", [
        rawPath,
      ]),
    ).toBe(expected);
  });

  test("preserves percent escapes in static-demo file names", async () => {
    setEnv("NEXT_PUBLIC_STATIC_WEBSITE_ONLY", "true");
    const { urlOfArtifact } = await loadFreshArtifactUtils();
    expect(
      urlOfArtifact({
        filepath: "/mnt/user-data/outputs/report%20final.md",
        threadId: "thread-1",
      }),
    ).toBe("/demo/threads/thread-1/user-data/outputs/report%2520final.md");
  });

  test("preserves markdown query and fragment suffixes on artifact URLs", async () => {
    const { resolveMarkdownArtifactURL, resolveMessageImageURL } =
      await loadFreshArtifactUtils();

    expect(
      resolveMarkdownArtifactURL(
        "/mnt/user-data/outputs/chart.png?v=2#detail",
        "thread-1",
      ),
    ).toBe(
      "/api/threads/thread-1/artifacts/mnt/user-data/outputs/chart.png?v=2#detail",
    );
    expect(
      resolveMessageImageURL(
        "/mnt/user-data/outputs/a%23b%3F.png?v=2#detail",
        "thread-1",
        [],
      ),
    ).toBe(
      "/api/threads/thread-1/artifacts/mnt/user-data/outputs/a%23b%3F.png?v=2#detail",
    );
  });

  test("encodes reserved characters in static demo artifact URLs", async () => {
    setEnv("NEXT_PUBLIC_STATIC_WEBSITE_ONLY", "true");

    const { urlOfArtifact } = await loadFreshArtifactUtils();

    expect(
      urlOfArtifact({
        filepath: "/mnt/user-data/outputs/a#b?.txt",
        threadId: "thread #1",
        download: true,
      }),
    ).toBe(
      "/demo/threads/thread%20%231/user-data/outputs/a%23b%3F.txt?download=true",
    );
  });

  test("returns stable artifact path references", async () => {
    const { extractArtifactsFromThread } = await loadFreshArtifactUtils();
    const threadWithoutArtifacts = { values: {} };
    const artifacts = ["/mnt/user-data/outputs/chart.png"];

    expect(extractArtifactsFromThread(threadWithoutArtifacts)).toBe(
      extractArtifactsFromThread(threadWithoutArtifacts),
    );
    expect(extractArtifactsFromThread({ values: { artifacts } })).toBe(
      artifacts,
    );
  });

  test("resolves absolute and relative message image paths", async () => {
    const { resolveMessageImageURL } = await loadFreshArtifactUtils();
    const artifacts = [
      "/mnt/user-data/outputs/aws-agent-overview.png",
      "/mnt/user-data/outputs/aws-agent-console-config.png",
      "/mnt/user-data/outputs/chart.png",
      "/mnt/user-data/outputs/a#b?.png",
    ];

    expect(
      resolveMessageImageURL("aws-agent-overview.png", "thread-1", artifacts),
    ).toBe(
      "/api/threads/thread-1/artifacts/mnt/user-data/outputs/aws-agent-overview.png",
    );
    expect(
      resolveMessageImageURL(
        "./aws-agent-overview.png#detail",
        "thread-1",
        artifacts,
      ),
    ).toBe(
      "/api/threads/thread-1/artifacts/mnt/user-data/outputs/aws-agent-overview.png#detail",
    );
    expect(
      resolveMessageImageURL(
        "/mnt/user-data/outputs/chart.png",
        "thread-1",
        artifacts,
      ),
    ).toBe("/api/threads/thread-1/artifacts/mnt/user-data/outputs/chart.png");
    expect(
      resolveMessageImageURL("outputs/chart.png", "thread-1", artifacts),
    ).toBe("/api/threads/thread-1/artifacts/mnt/user-data/outputs/chart.png");
    expect(
      resolveMessageImageURL("a%23b%3F.png#detail", "thread-1", artifacts),
    ).toBe(
      "/api/threads/thread-1/artifacts/mnt/user-data/outputs/a%23b%3F.png#detail",
    );
  });

  test("does not rewrite unregistered, ambiguous, or external message images", async () => {
    const { resolveMessageImageURL } = await loadFreshArtifactUtils();

    expect(resolveMessageImageURL("missing.png", "thread-1", [])).toBe(
      "missing.png",
    );
    expect(
      resolveMessageImageURL("shared.png", "thread-1", [
        "/mnt/user-data/outputs/first/shared.png",
        "/mnt/user-data/outputs/second/shared.png",
      ]),
    ).toBe("shared.png");
    expect(
      resolveMessageImageURL("../etc/secret.png", "thread-1", [
        "/mnt/user-data/outputs/secret.png",
      ]),
    ).toBe("../etc/secret.png");
    expect(
      resolveMessageImageURL("https://example.com/image.png", "thread-1", [
        "/mnt/user-data/outputs/image.png",
      ]),
    ).toBe("https://example.com/image.png");
  });

  test("resolveRelativeArtifactURL returns null when it cannot resolve", async () => {
    const { isRelativeArtifactReference, resolveRelativeArtifactURL } =
      await loadFreshArtifactUtils();
    const artifacts = [
      "/mnt/user-data/outputs/report.md",
      "/mnt/user-data/outputs/a/dup.md",
      "/mnt/user-data/outputs/b/dup.md",
    ];

    expect(
      resolveRelativeArtifactURL("./report.md#s1", "thread-1", artifacts),
    ).toBe(
      "/api/threads/thread-1/artifacts/mnt/user-data/outputs/report.md#s1",
    );
    expect(resolveRelativeArtifactURL("dup.md", "thread-1", artifacts)).toBe(
      null,
    );
    expect(resolveRelativeArtifactURL("none.md", "thread-1", artifacts)).toBe(
      null,
    );
    expect(
      resolveRelativeArtifactURL("../report.md", "thread-1", artifacts),
    ).toBe(null);

    expect(isRelativeArtifactReference("report.md")).toBe(true);
    expect(isRelativeArtifactReference("./a/b.md?x=1")).toBe(true);
    for (const href of [
      "../report.md",
      "/workspace/chats/x",
      "/mnt/user-data/outputs/report.md",
      "https://example.com/report.md",
      "mailto:a@example.com",
      "#section",
      "?q=1",
      "",
    ]) {
      expect(isRelativeArtifactReference(href)).toBe(false);
    }
  });

  test("collectThreadArtifactPaths adds present_files paths missing from state", async () => {
    const { collectThreadArtifactPaths } = await loadFreshArtifactUtils();
    const state = ["/mnt/user-data/outputs/a.md"];
    const messages = [
      { type: "human", id: "h", content: "go" },
      {
        type: "ai",
        id: "a1",
        content: "",
        tool_calls: [
          {
            id: "p1",
            name: "present_files",
            args: {
              filepaths: [
                "/mnt/user-data/outputs/a.md",
                "/mnt/user-data/outputs/b.zip",
                "outputs/relative-is-ignored.md",
              ],
            },
          },
        ],
      },
    ] as Parameters<typeof collectThreadArtifactPaths>[1];

    // Reopened thread: the /history head carries no artifacts.
    expect(collectThreadArtifactPaths([], messages)).toEqual([
      "/mnt/user-data/outputs/a.md",
      "/mnt/user-data/outputs/b.zip",
    ]);
    expect(collectThreadArtifactPaths(state, messages)).toEqual([
      "/mnt/user-data/outputs/a.md",
      "/mnt/user-data/outputs/b.zip",
    ]);
    // Without present_files the state array is returned as-is.
    expect(collectThreadArtifactPaths(state, [messages[0]!])).toBe(state);
  });

  describe("shared artifacts in thread history", () => {
    const origin = "source-thread";
    const sha256 = "a".repeat(64);
    const outputs = "/mnt/user-data/outputs";
    const receipt = `Successfully presented shared artifact; origin_thread_id=${origin}; sha256=${sha256}`;

    function handoff(id: string, path: string) {
      return {
        id,
        name: "present_shared_artifact",
        args: { path, origin_thread_id: origin, sha256 },
      };
    }

    function result(
      toolCallId: string,
      fields: Partial<ToolMessage> = {},
    ): ToolMessage {
      return {
        type: "tool",
        tool_call_id: toolCallId,
        content: receipt,
        ...fields,
      };
    }

    test("restores only handoffs with their own confirmed receipt", async () => {
      const { collectThreadArtifactPaths } = await loadFreshArtifactUtils();
      const delivered = `${outputs}/lesson.pptx`;
      const messages: Message[] = [
        {
          type: "ai",
          content: "",
          tool_calls: [
            handoff("delivered", delivered),
            handoff("failed", `${outputs}/failed.pptx`),
            handoff("pending", `${outputs}/pending.pptx`),
            handoff("wrong-hash", `${outputs}/wrong-hash.pptx`),
            handoff("error-status", `${outputs}/error-status.pptx`),
            handoff("ambiguous", `${outputs}/ambiguous.pptx`),
            handoff("ambiguous", `${outputs}/ambiguous-other.pptx`),
          ],
        },
        // History can serialize unnamed results with null. / 历史回执的名称可能为 null。
        { ...result("delivered"), name: null } as unknown as ToolMessage,
        result("failed", { content: "Error: Source artifact changed" }),
        result("unrelated"),
        result("wrong-hash", {
          content: receipt.replace(sha256, "b".repeat(64)),
        }),
        result("error-status", { status: "error" }),
        result("ambiguous"),
      ];

      expect(collectThreadArtifactPaths([], messages)).toEqual([delivered]);
      expect(collectThreadArtifactPaths([delivered], messages)).toEqual([
        delivered,
      ]);
    });

    test("restores a handoff once with identical success receipts", async () => {
      const { collectThreadArtifactPaths } = await loadFreshArtifactUtils();
      const delivered = `${outputs}/report.md`;
      const success = result("duplicate", {
        id: "receipt-1",
        name: "present_shared_artifact",
        status: "success",
        additional_kwargs: { deerflow_tool_meta: { status: "success" } },
      });
      const messages: Message[] = [
        {
          type: "ai",
          content: "",
          tool_calls: [handoff("duplicate", delivered)],
        },
        success,
        { ...success, id: "receipt-2" },
      ];

      expect(collectThreadArtifactPaths([], messages)).toEqual([delivered]);
    });

    test.each([
      ["an explicit error", { status: "error" }],
      [
        "different receipt text",
        { content: receipt.replace(origin, "other-thread") },
      ],
      ["a different tool name", { name: "present_files" }],
      [
        "an unknown status",
        { status: "pending" } as unknown as Partial<ToolMessage>,
      ],
      [
        "error metadata",
        { additional_kwargs: { deerflow_tool_meta: { status: "error" } } },
      ],
      [
        "partial success metadata",
        {
          additional_kwargs: {
            deerflow_tool_meta: { status: "partial_success" },
          },
        },
      ],
      ["malformed metadata", { additional_kwargs: { deerflow_tool_meta: {} } }],
    ] satisfies [string, Partial<ToolMessage>][])(
      "skips a handoff when a matching receipt has %s",
      async (_reason, fields) => {
        const { collectThreadArtifactPaths } = await loadFreshArtifactUtils();
        const messages: Message[] = [
          {
            type: "ai",
            content: "",
            tool_calls: [handoff("conflicting", `${outputs}/report.md`)],
          },
          result("conflicting", { id: "receipt-1", status: "success" }),
          result("conflicting", {
            id: "receipt-2",
            status: "success",
            ...fields,
          }),
        ];

        expect(collectThreadArtifactPaths([], messages)).toEqual([]);
      },
    );

    test("skips a handoff without a matching receipt", async () => {
      const { collectThreadArtifactPaths } = await loadFreshArtifactUtils();
      const messages: Message[] = [
        {
          type: "ai",
          content: "",
          tool_calls: [handoff("pending", `${outputs}/pending.md`)],
        },
        result("unrelated"),
      ];

      expect(collectThreadArtifactPaths([], messages)).toEqual([]);
    });

    test("keeps reused call IDs scoped to their assistant occurrence", async () => {
      const { collectThreadArtifactPaths } = await loadFreshArtifactUtils();
      const delivered = `${outputs}/first.md`;
      const first: AIMessage = {
        type: "ai",
        content: "",
        tool_calls: [handoff("reused", delivered)],
      };
      const second: AIMessage = {
        type: "ai",
        content: "",
        tool_calls: [handoff("reused", `${outputs}/second.md`)],
      };
      const messages = [
        first,
        result("reused", { id: "first-receipt" }),
        result("reused", { id: "retried-receipt" }),
        second,
        result("reused", { content: "Error: Destination already exists" }),
      ];

      expect(collectThreadArtifactPaths([], messages)).toEqual([delivered]);
    });

    test("restores the canonical output path and rejects escapes", async () => {
      const { collectThreadArtifactPaths } = await loadFreshArtifactUtils();
      const messages: Message[] = [
        {
          type: "ai",
          content: "",
          tool_calls: [
            handoff("canonicalized", `${outputs}//notes/../report%20one.md`),
            handoff("escape", `${outputs}/../outside.md`),
          ],
        },
        result("canonicalized"),
        result("escape"),
      ];

      expect(collectThreadArtifactPaths([], messages)).toEqual([
        `${outputs}/report%20one.md`,
      ]);
    });
  });

  test("builds encoded write-file URLs without undefined query parameters", async () => {
    const { buildWriteFileArtifactURL } = await loadFreshArtifactUtils();
    const filepath = "/mnt/user-data/outputs/a b#c?%20.md";
    expect(
      buildWriteFileArtifactURL({
        filepath: "/mnt/user-data/outputs/report.md",
        messageId: "ai-1",
        toolCallId: "call-1",
      }),
    ).toBe(
      "write-file:/mnt/user-data/outputs/report.md?message_id=ai-1&tool_call_id=call-1",
    );

    const withIds = new URL(
      buildWriteFileArtifactURL({
        filepath,
        messageId: "message #1",
        toolCallId: "call ?1",
      }),
    );
    expect(decodeURIComponent(withIds.pathname)).toBe(filepath);
    expect(withIds.searchParams.get("message_id")).toBe("message #1");
    expect(withIds.searchParams.get("tool_call_id")).toBe("call ?1");

    const withoutIds = buildWriteFileArtifactURL({ filepath });
    expect(withoutIds).not.toContain("undefined");
    expect(new URL(withoutIds).search).toBe("");
  });
});
