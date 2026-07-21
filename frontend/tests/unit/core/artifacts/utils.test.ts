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
      "/api/threads/thread-1/artifacts/mnt/user-data/outputs/a%23b%3F.txt",
    );
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
});
