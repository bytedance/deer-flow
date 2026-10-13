import { afterEach, describe, expect, it } from "@rstest/core";
import { cleanup, render, screen, waitFor } from "@testing-library/react";

import { ArtifactFilePreview } from "@/components/workspace/artifacts/artifact-file-preview";
import { I18nProvider } from "@/core/i18n/context";

afterEach(cleanup);

function preview(filepath: string, threadId: string, isMock = false) {
  return (
    <I18nProvider initialLocale="en-US">
      <ArtifactFilePreview
        content="![Chart](chart.png)"
        language="markdown"
        scrollKey={`${threadId}:${filepath}`}
        artifact={{ filepath, threadId, isMock }}
      />
    </I18nProvider>
  );
}

describe("Markdown artifact images", () => {
  it("resolves write-file preview images without a fetched document URL", async () => {
    render(preview("/mnt/user-data/outputs/report.md", "first"));
    expect((await screen.findByAltText("Chart")).getAttribute("src")).toBe(
      "/api/threads/first/artifacts/mnt/user-data/outputs/chart.png",
    );
  });

  it("updates image destinations when unchanged content moves to another artifact or thread", async () => {
    const { rerender } = render(
      preview("/mnt/user-data/outputs/one/report.md", "first"),
    );
    await screen.findByAltText("Chart");
    rerender(preview("/mnt/user-data/outputs/two/report.md", "first"));
    await waitFor(() =>
      expect(screen.getByAltText("Chart").getAttribute("src")).toBe(
        "/api/threads/first/artifacts/mnt/user-data/outputs/two/chart.png",
      ),
    );
    rerender(preview("/mnt/user-data/outputs/two/report.md", "second"));
    await waitFor(() =>
      expect(screen.getByAltText("Chart").getAttribute("src")).toBe(
        "/api/threads/second/artifacts/mnt/user-data/outputs/two/chart.png",
      ),
    );
  });

  it("updates unchanged content when switching to mock artifacts", async () => {
    const filepath = "/mnt/user-data/outputs/report.md";
    const { rerender } = render(preview(filepath, "first"));
    await screen.findByAltText("Chart");
    rerender(preview(filepath, "first", true));
    await waitFor(() =>
      expect(screen.getByAltText("Chart").getAttribute("src")).toBe(
        "/mock/api/threads/first/artifacts/mnt/user-data/outputs/chart.png",
      ),
    );
  });

  it.each([false, true])(
    "keeps sanitization with artifact context: %s",
    async (withContext) => {
      const { container } = render(
        <I18nProvider initialLocale="en-US">
          <ArtifactFilePreview
            content={
              '![Chart](chart.png)\n\n<img alt="Unsafe" src="javascript:alert(1)" onerror="alert(2)"><script>alert(3)</script>'
            }
            language="markdown"
            scrollKey="project-document"
            artifact={
              withContext
                ? {
                    filepath: "/mnt/user-data/outputs/report.md",
                    threadId: "first",
                  }
                : undefined
            }
          />
        </I18nProvider>,
      );
      expect((await screen.findByAltText("Chart")).getAttribute("src")).toBe(
        withContext
          ? "/api/threads/first/artifacts/mnt/user-data/outputs/chart.png"
          : "chart.png",
      );
      expect(
        container.querySelector("script, [onerror], [src^='javascript:']"),
      ).toBeNull();
    },
  );
});
