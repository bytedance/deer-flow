import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render } from "@testing-library/react";
import type { PropsWithChildren } from "react";

const mocks = rs.hoisted(() => ({
  artifactContent: {
    content: undefined as string | undefined,
    url: undefined as string | undefined,
    sha256: undefined as string | undefined,
    truncated: false,
    previewBytes: undefined as number | undefined,
    totalBytes: undefined as number | undefined,
    fullContentRequested: false,
    loadFullContent: rs.fn(),
    isLoading: false,
    error: undefined as unknown,
  },
}));

rs.mock("@/core/artifacts/hooks", () => ({
  useArtifactContent: () => mocks.artifactContent,
}));

rs.mock("@/components/workspace/messages/context", () => ({
  useThread: () => ({ thread: { isLoading: false }, isMock: false }),
}));

rs.mock("@/components/workspace/artifacts/context", () => ({
  useArtifacts: () => ({
    artifacts: [],
    setArtifacts: rs.fn(),
    selectedArtifact: null,
    autoSelect: false,
    select: rs.fn(),
    deselect: rs.fn(),
    open: true,
    autoOpen: false,
    setOpen: rs.fn(),
    drafts: {},
    setDrafts: rs.fn(),
    editingPath: null,
    setEditingPath: rs.fn(),
  }),
}));

rs.mock("@/core/auth/AuthProvider", () => ({
  useAuth: () => ({ user: null }),
}));

// Inspect the source passed to the editor without bundling CodeMirror.
rs.mock("@/components/workspace/code-editor", () => ({
  CodeEditor: ({ value, language }: { value: string; language: string }) => (
    <pre data-testid="artifact-source" data-language={language}>
      {value}
    </pre>
  ),
}));

rs.mock("@/core/config", () => ({
  getBackendBaseURL: () => "/backend",
}));

rs.mock("@/env", () => ({
  env: { NEXT_PUBLIC_STATIC_WEBSITE_ONLY: "false" },
}));

import { ArtifactFileDetail } from "@/components/workspace/artifacts/artifact-file-detail";
import { I18nProvider } from "@/core/i18n/context";

const THREAD_ID = "7cfa5f8f-a2f8-47ad-acbd-da7137baf990";

function Wrapper({ children }: PropsWithChildren) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return (
    <QueryClientProvider client={queryClient}>
      <I18nProvider initialLocale="en-US">{children}</I18nProvider>
    </QueryClientProvider>
  );
}

function renderDetail(filepath: string) {
  return render(
    <Wrapper>
      <ArtifactFileDetail filepath={filepath} threadId={THREAD_ID} />
    </Wrapper>,
  );
}

beforeEach(() => {
  mocks.artifactContent.content = undefined;
  mocks.artifactContent.sha256 = undefined;
});

describe("ArtifactFileDetail extensionless source files", () => {
  it.each([
    ["Dockerfile", "dockerfile", "FROM python:3.13\n"],
    ["Makefile", "makefile", "all:\n\techo hello\n"],
  ])("opens a stored %s as editable source", (filename, language, content) => {
    mocks.artifactContent.content = content;
    mocks.artifactContent.sha256 = "a".repeat(64);

    const view = renderDetail(`/mnt/user-data/outputs/${filename}`);
    const source = view.getByTestId("artifact-source");

    expect(source.textContent).toBe(content);
    expect(source.getAttribute("data-language")).toBe(language);
    expect(view.getByRole("button", { name: "Edit" })).toBeTruthy();
  });
});

describe("ArtifactFileDetail unknown file types", () => {
  it.each(["constructor", "data.constructor", "__proto__", "data.__proto__"])(
    "keeps %s on the download fallback instead of passing an invalid language to the editor",
    (filename) => {
      mocks.artifactContent.content = "file contents";
      mocks.artifactContent.sha256 = "a".repeat(64);

      const view = renderDetail(`/mnt/user-data/outputs/${filename}`);

      expect(view.queryByTestId("artifact-source")).toBeNull();
      expect(view.queryByRole("button", { name: "Edit" })).toBeNull();
      expect(
        view.getByRole("link", { name: "Download" }).getAttribute("href"),
      ).toBe(
        `/backend/api/threads/${THREAD_ID}/artifacts/mnt/user-data/outputs/${filename}?download=true`,
      );
    },
  );
});

afterEach(() => {
  cleanup();
  rs.clearAllMocks();
});

describe("ArtifactFileDetail browser-preview iframe", () => {
  it("renders a PDF in an iframe WITHOUT the sandbox attribute", () => {
    // Chromium blocks its built-in PDF viewer inside sandbox=""; the bytes
    // are safe inline because the endpoint declares application/pdf with
    // X-Content-Type-Options: nosniff.
    const { container } = renderDetail("/mnt/user-data/outputs/report.pdf");
    const frame = container.querySelector("iframe");
    if (!(frame instanceof HTMLIFrameElement)) {
      throw new Error("preview iframe not rendered");
    }
    expect(frame.getAttribute("sandbox")).toBeNull();
    expect(frame.getAttribute("src")).toBe(
      `/backend/api/threads/${THREAD_ID}/artifacts/mnt/user-data/outputs/report.pdf`,
    );
    // Untitled frames have no accessible name (the sibling preview iframe
    // keeps "Artifact preview"); dropping this regressed WCAG frame titles.
    expect(frame.getAttribute("title")).toBe("report.pdf");
  });

  it("keeps the empty sandbox for images and other passive binaries", () => {
    const { container } = renderDetail("/mnt/user-data/outputs/chart.png");
    const frame = container.querySelector("iframe");
    if (!(frame instanceof HTMLIFrameElement)) {
      throw new Error("preview iframe not rendered");
    }
    expect(frame.getAttribute("sandbox")).toBe("");
    expect(frame.getAttribute("src")).toBe(
      `/backend/api/threads/${THREAD_ID}/artifacts/mnt/user-data/outputs/chart.png`,
    );
  });
});
