import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import type { PropsWithChildren } from "react";

rs.mock("@/core/artifacts/loader", () => ({
  loadArtifactContent: rs.fn(),
  loadArtifactContentFromToolCall: rs.fn(),
}));

import { ArtifactViewer } from "@/components/workspace/artifacts/artifact-viewer";
import { loadArtifactContent } from "@/core/artifacts/loader";
import { urlOfArtifact } from "@/core/artifacts/utils";
import { I18nProvider } from "@/core/i18n/context";

const mockedLoadArtifactContent = rs.mocked(loadArtifactContent);
const filepath = "/mnt/user-data/outputs/report.md";
const threadId = "7cfa5f8f-a2f8-47ad-acbd-da7137baf990";

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

function renderViewer(props?: { isMock?: boolean }) {
  return render(
    <Wrapper>
      <ArtifactViewer filepath={filepath} threadId={threadId} {...props} />
    </Wrapper>,
  );
}

describe("ArtifactViewer", () => {
  beforeEach(() => {
    mockedLoadArtifactContent.mockResolvedValue({
      content: "# Quarterly report\n\nRevenue is up.",
      url: urlOfArtifact({ filepath, threadId }),
      sha256: undefined,
      truncated: false,
      previewBytes: 36,
      totalBytes: 36,
    });
  });

  afterEach(() => {
    cleanup();
    mockedLoadArtifactContent.mockReset();
  });

  it("renders the markdown artifact with the app's markdown renderer", async () => {
    const { container } = renderViewer();

    await waitFor(() => {
      expect(container.querySelector("h1")?.textContent).toContain(
        "Quarterly report",
      );
    });
    expect(container.textContent).not.toContain("# Quarterly report");
    expect(mockedLoadArtifactContent).toHaveBeenCalledWith({
      filepath,
      threadId,
      isMock: false,
      full: false,
    });
  });

  it("loads the mock artifact source when opened from a mock thread", async () => {
    renderViewer({ isMock: true });

    await waitFor(() => {
      expect(mockedLoadArtifactContent).toHaveBeenCalledWith({
        filepath,
        threadId,
        isMock: true,
        full: false,
      });
    });
  });

  it("fetches the whole file when a truncated preview is expanded", async () => {
    mockedLoadArtifactContent.mockImplementation(async ({ full }) => ({
      content: full ? "# Full report\n\nEverything." : "# Full rep",
      url: urlOfArtifact({ filepath, threadId }),
      sha256: undefined,
      truncated: !full,
      previewBytes: full ? 27 : 10,
      totalBytes: 27,
    }));
    const { container } = renderViewer();

    const loadFull = await screen.findByRole("button", {
      name: "Load full file",
    });
    loadFull.click();

    await waitFor(() => {
      expect(container.textContent).toContain("Everything.");
    });
    expect(mockedLoadArtifactContent).toHaveBeenLastCalledWith({
      filepath,
      threadId,
      isMock: false,
      full: true,
    });
    expect(screen.queryByRole("button", { name: "Load full file" })).toBe(null);
  });

  it("offers a download when the artifact cannot be loaded", async () => {
    mockedLoadArtifactContent.mockRejectedValue(new Error("boom"));

    renderViewer();

    const download = await screen.findByRole("link", { name: /download/i });
    expect(download.getAttribute("href")).toBe(
      urlOfArtifact({ filepath, threadId, download: true }),
    );
  });
});
