import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

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
  vi.resetModules();
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

  test("recognizes artifact virtual paths with and without leading slash", async () => {
    const { isArtifactVirtualPath } = await loadFreshArtifactUtils();

    expect(isArtifactVirtualPath("/mnt/user-data/outputs/result.docx")).toBe(
      true,
    );
    expect(isArtifactVirtualPath("mnt/user-data/outputs/result.docx")).toBe(
      true,
    );
    expect(isArtifactVirtualPath("/workspace/chats/thread-1")).toBe(false);
  });

  test("normalizes artifact virtual paths to include a leading slash", async () => {
    const { normalizeArtifactVirtualPath } = await loadFreshArtifactUtils();

    expect(
      normalizeArtifactVirtualPath("mnt/user-data/outputs/result.docx"),
    ).toBe("/mnt/user-data/outputs/result.docx");
    expect(
      normalizeArtifactVirtualPath("/mnt/user-data/outputs/result.docx"),
    ).toBe("/mnt/user-data/outputs/result.docx");
  });

  test("builds artifact URLs for paths with and without leading slash", async () => {
    setEnv("NEXT_PUBLIC_BACKEND_BASE_URL", "http://localhost:2026");

    const { resolveArtifactURL } = await loadFreshArtifactUtils();

    expect(
      resolveArtifactURL("/mnt/user-data/outputs/result.docx", "thread-1"),
    ).toBe(
      "http://localhost:2026/api/threads/thread-1/artifacts/mnt/user-data/outputs/result.docx",
    );
    expect(
      resolveArtifactURL("mnt/user-data/outputs/result.docx", "thread-1"),
    ).toBe(
      "http://localhost:2026/api/threads/thread-1/artifacts/mnt/user-data/outputs/result.docx",
    );
  });

  test("normalizes artifact URLs for direct and mock downloads", async () => {
    setEnv("NEXT_PUBLIC_BACKEND_BASE_URL", "http://localhost:2026");

    const { urlOfArtifact } = await loadFreshArtifactUtils();

    expect(
      urlOfArtifact({
        filepath: "mnt/user-data/outputs/result.docx",
        threadId: "thread-1",
      }),
    ).toBe(
      "http://localhost:2026/api/threads/thread-1/artifacts/mnt/user-data/outputs/result.docx",
    );
    expect(
      urlOfArtifact({
        filepath: "mnt/user-data/outputs/result.docx",
        threadId: "thread-1",
        download: true,
        isMock: true,
      }),
    ).toBe(
      "http://localhost:2026/mock/api/threads/thread-1/artifacts/mnt/user-data/outputs/result.docx?download=true",
    );
  });

  test("normalizes static demo artifact paths without a leading slash", async () => {
    setEnv("NEXT_PUBLIC_STATIC_WEBSITE_ONLY", "true");

    const { resolveArtifactURL, urlOfArtifact } =
      await loadFreshArtifactUtils();

    expect(
      urlOfArtifact({
        filepath: "mnt/user-data/outputs/index.html",
        threadId: "thread-1",
      }),
    ).toBe("/demo/threads/thread-1/user-data/outputs/index.html");
    expect(
      resolveArtifactURL("mnt/user-data/outputs/style.css", "thread-1"),
    ).toBe("/demo/threads/thread-1/user-data/outputs/style.css");
  });
});
