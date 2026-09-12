import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";

const mocks = rs.hoisted(() => ({
  load: rs.fn(),
  download: rs.fn(),
  handoff: rs.fn(),
}));
rs.mock("@/core/skills/export", () => ({
  loadSkillExportManifest: mocks.load,
  downloadSkillExport: mocks.download,
  handOffSkillDownload: mocks.handoff,
  SkillExportRequestError: class extends Error {
    constructor(
      readonly status: number,
      readonly code: string,
      message: string,
    ) {
      super(message);
    }
  },
}));
rs.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({ locale: "en-US", t: enUS }),
}));
import SkillExportDialog from "@/components/workspace/settings/skill-export-dialog";
import { enUS } from "@/core/i18n/locales/en-US";
import {
  SkillExportRequestError,
  type SkillExportManifest,
} from "@/core/skills/export";

const manifest: SkillExportManifest = {
  skill_name: "demo",
  revision: "a".repeat(64),
  can_export: true,
  file_count: 51,
  directory_count: 1,
  total_bytes: 51,
  files: Array.from({ length: 51 }, (_, i) => ({
    path: `file-${i}.txt`,
    type: "file",
    size: 1,
    executable: false,
  })),
  requirements: {
    compatibility: null,
    allowed_tools: null,
    required_secrets: [{ name: "DEMO_KEY", optional: true }],
  },
  warnings: [],
  blockers: [],
};
beforeEach(() => {
  mocks.load.mockReset().mockResolvedValue(manifest);
  mocks.download.mockReset();
  mocks.handoff.mockReset();
});
afterEach(cleanup);

describe("export dialog lifecycle", () => {
  it("pages the file list and distinguishes undeclared dependencies", async () => {
    render(<SkillExportDialog name="demo" onClose={rs.fn()} />);
    await screen.findByText("DEMO_KEY (optional)");
    expect(screen.getAllByText("Not declared")).toHaveLength(2);
    expect(screen.queryByText("file-50.txt")).toBeNull();
    fireEvent.click(screen.getByText("Next 50 files"));
    expect(screen.getByText("file-50.txt")).toBeTruthy();
    expect(screen.queryByText("file-0.txt")).toBeNull();
  });
  it("requires refreshed preview after a conflict", async () => {
    mocks.download.mockRejectedValue(
      new SkillExportRequestError(409, "skill_changed", "changed"),
    );
    render(<SkillExportDialog name="demo" onClose={rs.fn()} />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Download .skill" }),
    );
    await screen.findByText(
      "The skill changed. Refresh the file list before downloading.",
    );
    expect(
      screen
        .getByRole("button", {
          name: "Download .skill",
        })
        .hasAttribute("disabled"),
    ).toBe(true);
    expect(mocks.handoff).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Refresh file list" }));
    await waitFor(() => expect(mocks.load).toHaveBeenCalledTimes(2));
  });
  it("ignores a download that finishes after unmount even if fetch ignores abort", async () => {
    let resolve!: (blob: Blob) => void;
    mocks.download.mockImplementation(
      () =>
        new Promise<Blob>((r) => {
          resolve = r;
        }),
    );
    const view = render(<SkillExportDialog name="demo" onClose={rs.fn()} />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Download .skill" }),
    );
    const signal = mocks.download.mock.calls[0]![2] as AbortSignal;
    view.unmount();
    expect(signal.aborted).toBe(true);
    await act(async () => {
      resolve(new Blob(["zip"]));
    });
    expect(mocks.handoff).not.toHaveBeenCalled();
  });
  it("announces handoff only after the complete blob arrives", async () => {
    mocks.download.mockResolvedValue(new Blob(["zip"]));
    render(<SkillExportDialog name="demo" onClose={rs.fn()} />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Download .skill" }),
    );
    await screen.findByText("File handed to your browser for download.");
    expect(mocks.handoff).toHaveBeenCalledTimes(1);
  });
});
