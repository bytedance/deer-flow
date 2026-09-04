import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";

const artifactState = rs.hoisted(() => ({
  select: rs.fn(),
  setOpen: rs.fn(),
}));
const archiveState = rs.hoisted(() => {
  class RequestError extends Error {
    readonly status: number;

    constructor(status: number, message: string) {
      super(message);
      this.status = status;
    }
  }

  return {
    download: rs.fn(),
    manifest: rs.fn(),
    RequestError,
    toastError: rs.fn(),
  };
});

rs.mock("@/core/auth/AuthProvider", () => ({
  useAuth: () => ({ user: null }),
}));
rs.mock("@/components/workspace/artifacts/context", () => ({
  useArtifacts: () => artifactState,
}));
rs.mock("@/core/artifacts/api", () => ({
  ArtifactRequestError: archiveState.RequestError,
  downloadArtifactArchive: archiveState.download,
  getArtifactArchiveManifest: archiveState.manifest,
  MAX_ARTIFACT_ARCHIVE_FILES: 50,
}));
rs.mock("sonner", () => ({
  toast: { error: archiveState.toastError, success: rs.fn() },
}));

import { ArtifactFileList } from "@/components/workspace/artifacts/artifact-file-list";
import { ArtifactRequestError } from "@/core/artifacts/api";
import { I18nContext } from "@/core/i18n/context";
import { enUS } from "@/core/i18n/locales/en-US";

const files = [
  "/mnt/user-data/outputs/report.md",
  "/mnt/user-data/outputs/data.csv",
];

function renderList(
  props: Partial<React.ComponentProps<typeof ArtifactFileList>> = {},
) {
  const componentProps = { files, threadId: "thread-1", ...props };
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const component = (
    nextProps: React.ComponentProps<typeof ArtifactFileList>,
  ) => (
    <QueryClientProvider client={queryClient}>
      <I18nContext.Provider
        value={{ locale: "en-US", setLocale: () => undefined, t: enUS }}
      >
        <ArtifactFileList {...nextProps} />
      </I18nContext.Provider>
    </QueryClientProvider>
  );
  const result = render(component(componentProps));
  return {
    ...result,
    rerenderList: (
      nextProps: Partial<React.ComponentProps<typeof ArtifactFileList>>,
    ) => result.rerender(component({ ...componentProps, ...nextProps })),
  };
}

afterEach(cleanup);
afterEach(() => {
  rs.restoreAllMocks();
});

describe("ArtifactFileList archive download", () => {
  it("offers a branch-local run accepted by the manifest ownership check", async () => {
    archiveState.manifest.mockResolvedValue({ fileCount: 2 });
    renderList({ runId: "branch-run", threadId: "branch-thread" });

    expect(
      await screen.findByRole("button", {
        name: "Download current versions (2 files)",
      }),
    ).toBeTruthy();
    expect(archiveState.manifest).toHaveBeenCalledWith({
      runId: "branch-run",
      threadId: "branch-thread",
    });
    expect(
      screen.getByText(
        "The file list comes from this response. Contents are the current versions and may have changed.",
      ),
    ).toBeTruthy();
  });

  it("uses the verified receipt count instead of attempted tool arguments", async () => {
    archiveState.manifest.mockResolvedValue({ fileCount: 3 });
    renderList({ runId: "run-1" });

    expect(
      await screen.findByRole("button", {
        name: "Download current versions (3 files)",
      }),
    ).toBeTruthy();
  });

  it("does not offer an archive when only one attempted file was delivered", async () => {
    archiveState.manifest.mockResolvedValue({ fileCount: 1 });
    renderList({ runId: "run-1" });

    await waitFor(() => {
      expect(archiveState.manifest).toHaveBeenCalledWith({
        runId: "run-1",
        threadId: "thread-1",
      });
    });
    expect(
      screen.queryByRole("button", {
        name: /Download current versions/,
      }),
    ).toBeNull();
  });

  it("does not offer an archive outside a run-scoped delivery", () => {
    renderList();

    expect(
      screen.queryByRole("button", {
        name: /Download current versions/,
      }),
    ).toBeNull();
  });

  it("does not offer an archive for a single verified file", async () => {
    archiveState.manifest.mockResolvedValue({ fileCount: 1 });
    renderList({ files: files.slice(0, 1), runId: "run-1" });

    await waitFor(() => {
      expect(archiveState.manifest).toHaveBeenCalled();
    });
    expect(
      screen.queryByRole("button", {
        name: /Download current versions/,
      }),
    ).toBeNull();
  });

  it("does not offer an archive above the server file-count limit", async () => {
    archiveState.manifest.mockResolvedValue({ fileCount: 51 });
    renderList({ runId: "run-1" });

    await waitFor(() => {
      expect(archiveState.manifest).toHaveBeenCalled();
    });
    expect(
      screen.queryByRole("button", {
        name: /Download current versions/,
      }),
    ).toBeNull();
  });

  it("does not offer an archive when the current thread cannot download it", () => {
    renderList({ archiveDownloadsEnabled: false, runId: "run-1" });

    expect(
      screen.queryByRole("button", {
        name: /Download current versions/,
      }),
    ).toBeNull();
  });

  it("hides a cached archive while downloads are disabled", async () => {
    archiveState.manifest.mockResolvedValue({ fileCount: 2 });
    const { rerenderList } = renderList({ runId: "run-1" });
    await screen.findByRole("button", {
      name: "Download current versions (2 files)",
    });

    rerenderList({ archiveDownloadsEnabled: false });

    expect(
      screen.queryByRole("button", {
        name: /Download current versions/,
      }),
    ).toBeNull();
  });

  it("hides an inherited run when the thread ownership check rejects it", async () => {
    archiveState.manifest.mockRejectedValue(
      new ArtifactRequestError(404, "Run parent-run not found"),
    );
    renderList({ runId: "parent-run" });

    await waitFor(() => {
      expect(archiveState.manifest).toHaveBeenCalledWith({
        runId: "parent-run",
        threadId: "thread-1",
      });
    });
    expect(
      screen.queryByRole("button", {
        name: /Download current versions/,
      }),
    ).toBeNull();
  });

  it("downloads the archive and releases its object URL", async () => {
    archiveState.manifest.mockResolvedValue({ fileCount: 2 });
    const blob = new Blob(["zip"]);
    archiveState.download.mockResolvedValue({
      blob,
      filename: "artifacts-run-1.zip",
    });
    const createObjectURL = rs
      .spyOn(URL, "createObjectURL")
      .mockReturnValue("blob:archive");
    const revokeObjectURL = rs.spyOn(URL, "revokeObjectURL");
    let downloadedFilename: string | undefined;
    rs.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      downloadedFilename = this.download;
    });
    renderList({ runId: "run-1" });

    fireEvent.click(
      await screen.findByRole("button", {
        name: "Download current versions (2 files)",
      }),
    );

    await waitFor(() => {
      expect(archiveState.download).toHaveBeenCalledWith({
        runId: "run-1",
        threadId: "thread-1",
      });
      expect(downloadedFilename).toBe("artifacts-run-1.zip");
      expect(createObjectURL).toHaveBeenCalledWith(blob);
      expect(revokeObjectURL).toHaveBeenCalledWith("blob:archive");
    });
  });

  it("reports archive download failures", async () => {
    archiveState.manifest.mockResolvedValue({ fileCount: 2 });
    archiveState.download.mockRejectedValue(new Error("network down"));
    renderList({ runId: "run-1" });

    fireEvent.click(
      await screen.findByRole("button", {
        name: "Download current versions (2 files)",
      }),
    );

    await waitFor(() => {
      expect(archiveState.toastError).toHaveBeenCalledWith(
        "Failed to download artifact archive.",
      );
    });
  });

  it("shows actionable archive errors returned by the server", async () => {
    archiveState.manifest.mockResolvedValue({ fileCount: 2 });
    archiveState.download.mockRejectedValue(
      new ArtifactRequestError(
        413,
        "An artifact archive can contain at most 50 files",
      ),
    );
    renderList({ runId: "run-1" });

    fireEvent.click(
      await screen.findByRole("button", {
        name: "Download current versions (2 files)",
      }),
    );

    await waitFor(() => {
      expect(archiveState.toastError).toHaveBeenCalledWith(
        "An artifact archive can contain at most 50 files",
      );
    });
  });
});
