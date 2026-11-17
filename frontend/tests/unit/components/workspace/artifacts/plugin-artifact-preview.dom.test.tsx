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
import type { ArtifactPreviewContext } from "@/core/extensions/contracts";

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
  rs.unstubAllGlobals();
});

test("switching files aborts, disposes and isolates the previous mount", async () => {
  setup();
  state.read.mockResolvedValue({
    bytes: new ArrayBuffer(4),
    etag: '"revision"',
  });
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

test("run completion reloads the open file and fences the previous renderer", async () => {
  setup();
  const contexts: ArtifactPreviewContext[] = [];
  const dispose = rs.fn();
  state.mount.mockImplementation(
    (_root: HTMLElement, context: ArtifactPreviewContext) => {
      contexts.push(context);
      void context.readFile();
      return { dispose };
    },
  );
  state.read.mockResolvedValue({ bytes: new ArrayBuffer(4), etag: '"v1"' });
  const props = { filepath: "/refresh.xlsx", threadId: "thread" };
  const view = render(<PluginArtifactPreview {...props} isRunning={false} />);
  await act(async () => {
    await Promise.resolve();
  });
  view.rerender(<PluginArtifactPreview {...props} isRunning />);
  expect(state.read).toHaveBeenCalledTimes(1);
  state.read.mockResolvedValue({ bytes: new ArrayBuffer(5), etag: '"v2"' });
  view.rerender(<PluginArtifactPreview {...props} isRunning={false} />);
  await act(async () => {
    await Promise.resolve();
  });
  expect(state.read).toHaveBeenCalledTimes(2);
  expect(contexts[0]!.signal.aborted).toBe(true);
  expect(dispose).toHaveBeenCalledTimes(1);
  expect(contexts[1]!.signal.aborted).toBe(false);
});

for (const etag of ['"lan-revision"', null]) {
  test(`reads on an insecure origin with ETag ${etag ?? "absent"}`, async () => {
    setup();
    rs.stubGlobal("crypto", { subtle: undefined });
    const bytes = new ArrayBuffer(4);
    state.read.mockResolvedValue({ bytes, etag });
    const contexts: ArtifactPreviewContext[] = [];
    state.mount.mockImplementation(
      (_root: HTMLElement, context: ArtifactPreviewContext) => {
        contexts.push(context);
        return { dispose: rs.fn() };
      },
    );
    const props = {
      filepath: `/insecure-${etag ?? "absent"}.xlsx`,
      threadId: "thread",
    };
    const view = render(<PluginArtifactPreview {...props} />);
    await expect(contexts[0]!.readFile()).resolves.toBe(bytes);
    contexts[0]!.saveReadingState?.({ sheet: 2 });
    view.unmount();
    render(<PluginArtifactPreview {...props} />);
    await expect(contexts[1]!.readFile()).resolves.toBe(bytes);
    expect(contexts[1]!.getReadingState?.()).toEqual(
      etag ? { sheet: 2 } : undefined,
    );
    if (etag) {
      state.read.mockResolvedValue({ bytes, etag: '"new-revision"' });
      await contexts[1]!.readFile();
      expect(contexts[1]!.getReadingState?.()).toBeUndefined();
    }
  });
}

test("a failed optional digest cannot fail the file read", async () => {
  setup();
  rs.stubGlobal("crypto", {
    subtle: { digest: rs.fn().mockRejectedValue(new Error("unavailable")) },
  });
  const bytes = new ArrayBuffer(4);
  state.read.mockResolvedValue({ bytes, etag: null });
  let context: ArtifactPreviewContext;
  state.mount.mockImplementation(
    (_root: HTMLElement, value: ArtifactPreviewContext) => {
      context = value;
      return { dispose: rs.fn() };
    },
  );
  render(
    <PluginArtifactPreview filepath="/digest-failure.xlsx" threadId="thread" />,
  );
  await expect(context!.readFile()).resolves.toBe(bytes);
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
