import { afterEach, describe, expect, it, rs } from "@rstest/core";
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
  return render(
    <I18nContext.Provider
      value={{ locale: "en-US", setLocale: () => undefined, t: enUS }}
    >
      <ArtifactFileList {...componentProps} />
    </I18nContext.Provider>,
  );
}

afterEach(cleanup);
afterEach(() => {
  rs.restoreAllMocks();
});

describe("ArtifactFileList archive download", () => {
  it("offers the current versions of a run's multi-file delivery", () => {
    renderList({ runId: "run-1" });

    expect(
      screen.getByRole("button", {
        name: "Download current versions (2 files)",
      }),
    ).toBeTruthy();
    expect(
      screen.getByText(
        "The file list comes from this response. Contents are the current versions and may have changed.",
      ),
    ).toBeTruthy();
  });

  it("uses the run-wide file count when the action is anchored to one group", () => {
    renderList({ archiveFileCount: 3, runId: "run-1" });

    expect(
      screen.getByRole("button", {
        name: "Download current versions (3 files)",
      }),
    ).toBeTruthy();
  });

  it("does not offer an archive outside a run-scoped delivery", () => {
    renderList();

    expect(
      screen.queryByRole("button", {
        name: /Download current versions/,
      }),
    ).toBeNull();
  });

  it("does not offer an archive for a single file", () => {
    renderList({ files: files.slice(0, 1), runId: "run-1" });

    expect(
      screen.queryByRole("button", {
        name: /Download current versions/,
      }),
    ).toBeNull();
  });

  it("does not offer an archive above the server file-count limit", () => {
    renderList({ archiveFileCount: 51, runId: "run-1" });

    expect(
      screen.queryByRole("button", {
        name: /Download current versions/,
      }),
    ).toBeNull();
  });

  it("downloads the archive and releases its object URL", async () => {
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
      screen.getByRole("button", {
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
    archiveState.download.mockRejectedValue(new Error("network down"));
    renderList({ runId: "run-1" });

    fireEvent.click(
      screen.getByRole("button", {
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
    archiveState.download.mockRejectedValue(
      new ArtifactRequestError(
        413,
        "An artifact archive can contain at most 50 files",
      ),
    );
    renderList({ runId: "run-1" });

    fireEvent.click(
      screen.getByRole("button", {
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
