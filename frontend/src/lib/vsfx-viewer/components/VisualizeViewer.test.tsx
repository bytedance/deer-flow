import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { VisualizeViewer } from "@/lib/vsfx-viewer/components/VisualizeViewer";
import { render, screen, waitFor } from "@/test/render";

const viewerState = {
  dispose: vi.fn(),
  initialize: vi.fn(),
  open: vi.fn(),
};

vi.mock("@/lib/vsfx-viewer/runtime/Viewer", () => ({
  Viewer: vi.fn().mockImplementation(() => viewerState),
}));

describe("VisualizeViewer", () => {
  beforeEach(() => {
    viewerState.dispose.mockReset();
    viewerState.initialize.mockReset();
    viewerState.open.mockReset();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  test("initializes a mocked viewer, reports progress, and disposes on unmount", async () => {
    let resolveOpen: (() => void) | undefined;

    viewerState.initialize.mockImplementation(async ({ onProgress }) => {
      onProgress?.({ loaded: 25, percent: 25, total: 100 });
    });
    viewerState.open.mockImplementation(
      () =>
        new Promise<void>((resolve) => {
          resolveOpen = resolve;
        }),
    );

    const data = new Uint8Array([1, 2, 3]).buffer;
    const { unmount } = render(
      <VisualizeViewer data={data} filename="sample.vsfx" />,
    );

    expect(screen.getByTestId("vsfx-visualize-viewer")).toBeInTheDocument();

    await waitFor(() => {
      expect(viewerState.initialize).toHaveBeenCalledTimes(1);
    });

    expect(screen.getByText("25%")).toBeInTheDocument();

    resolveOpen?.();

    await waitFor(() => {
      expect(viewerState.open).toHaveBeenCalledWith({
        data,
        filename: "sample.vsfx",
      });
    });

    unmount();

    expect(viewerState.dispose).toHaveBeenCalledTimes(1);
  });
});
