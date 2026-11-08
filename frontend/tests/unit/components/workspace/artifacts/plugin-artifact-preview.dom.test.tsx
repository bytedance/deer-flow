import { afterEach, expect, rs, test } from "@rstest/core";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";

const state = rs.hoisted(() => ({
  user: { id: "owner" } as { id: string } | null,
  entries: [] as unknown[],
  mount: rs.fn(),
  read: rs.fn(),
}));
rs.mock("@/core/auth/AuthProvider", () => ({
  useAuth: () => ({ user: state.user }),
}));
rs.mock("@/core/extensions/hooks", () => ({
  useFrontendExtensions: () => ({ data: state.entries, isLoading: false }),
}));
rs.mock("@/core/artifacts/binary-preview", () => ({
  readPreviewFile: state.read,
}));
rs.mock("@/core/config", () => ({ getBackendBaseURL: () => "" }));
rs.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({
    locale: "en-US",
    t: {
      artifactPreview: {
        unavailable: "Unavailable",
        previewFailed: "Preview failed",
      },
      common: { download: "Download", retry: "Retry" },
    },
  }),
}));
rs.mock("@/components/workspace/artifacts/artifact-file-preview", () => ({
  ArtifactDownloadFallback: () => <div>Unavailable</div>,
  ArtifactPreviewError: ({ onRetry }: { onRetry?: () => void }) => (
    <div>
      Preview failed<button onClick={onRetry}>Retry</button>
    </div>
  ),
}));

import { PluginArtifactPreview } from "@/components/workspace/artifacts/plugin-artifact-preview";

function setup(viewerId = "owner", enabled = true) {
  state.user = { id: "owner" };
  state.entries = [
    {
      namespace: "test",
      viewer_id: viewerId,
      settings: { enabled },
      extension: {
        apiVersion: 1,
        module: "test",
        artifactPreviews: [
          { id: "office", extensions: ["xlsx"], mount: state.mount },
        ],
      },
    },
  ];
}
afterEach(() => {
  cleanup();
  state.mount.mockReset();
  state.read.mockReset();
});

test("switching files aborts, disposes and isolates the previous mount", async () => {
  setup();
  state.read.mockResolvedValue(new ArrayBuffer(4));
  const contexts: {
    signal: AbortSignal;
    onError: () => void;
    readFile: () => Promise<ArrayBuffer>;
  }[] = [];
  const roots: HTMLElement[] = [];
  const dispose = rs.fn();
  state.mount.mockImplementation(
    (root: HTMLElement, context: (typeof contexts)[number]) => {
      roots.push(root);
      contexts.push(context);
      root.textContent = "Workbook";
      return { dispose };
    },
  );
  const view = render(
    <PluginArtifactPreview
      filepath="/mnt/user-data/uploads/a.xlsx"
      threadId="thread"
    />,
  );
  expect(screen.getByLabelText("a.xlsx").shadowRoot?.textContent).toBe(
    "Workbook",
  );
  await contexts[0]!.readFile();
  expect(state.read).toHaveBeenCalledWith(
    expect.stringContaining(
      "/api/threads/thread/artifacts/mnt/user-data/uploads/a.xlsx",
    ),
    contexts[0]!.signal,
  );
  view.rerender(
    <PluginArtifactPreview
      filepath="/mnt/user-data/uploads/b.xlsx"
      threadId="thread"
    />,
  );
  expect(contexts[0]!.signal.aborted).toBe(true);
  expect(dispose).toHaveBeenCalledTimes(1);
  expect(roots[0]!.isConnected).toBe(false);
  contexts[0]!.onError();
  expect(screen.queryByText("Preview failed")).toBeNull();
  view.unmount();
  expect(contexts[1]!.signal.aborted).toBe(true);
  expect(dispose).toHaveBeenCalledTimes(2);
});

test("synchronous renderer failure shows a download fallback", () => {
  setup();
  state.mount.mockImplementation(() => {
    throw new Error("parser failed");
  });
  render(<PluginArtifactPreview filepath="/a.xlsx" threadId="thread" />);
  expect(screen.getByText("Preview failed")).toBeTruthy();
  expect(state.mount).toHaveBeenCalledTimes(1);
});

test("retry disposes the failed mount and ignores stale callbacks", () => {
  setup();
  const contexts: { signal: AbortSignal; onError: () => void }[] = [];
  const dispose = rs.fn();
  state.mount.mockImplementation(
    (root: HTMLElement, context: (typeof contexts)[number]) => {
      contexts.push(context);
      root.textContent = "Workbook";
      return { dispose };
    },
  );
  render(<PluginArtifactPreview filepath="/a.xlsx" threadId="thread" />);
  act(() => contexts[0]!.onError());
  expect(contexts[0]!.signal.aborted).toBe(true);
  expect(dispose).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole("button", { name: "Retry" }));
  expect(state.mount).toHaveBeenCalledTimes(2);
  expect(contexts[1]!.signal.aborted).toBe(false);
  act(() => contexts[0]!.onError());
  expect(screen.queryByText("Preview failed")).toBeNull();
  expect(screen.getByLabelText("a.xlsx").shadowRoot?.textContent).toBe(
    "Workbook",
  );
});

for (const kind of ["other-viewer", "disabled", "unsupported", "signed-out"]) {
  test(`does not mount a renderer when ${kind}`, () => {
    setup(
      kind === "other-viewer" ? "someone-else" : "owner",
      kind !== "disabled",
    );
    if (kind === "signed-out") state.user = null;
    render(
      <PluginArtifactPreview
        filepath={kind === "unsupported" ? "/a.xls" : "/a.xlsx"}
        threadId="thread"
      />,
    );
    expect(screen.getByText("Unavailable")).toBeTruthy();
    expect(state.mount).not.toHaveBeenCalled();
  });
}
