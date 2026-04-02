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
    vi.spyOn(window, "requestAnimationFrame").mockImplementation((callback: FrameRequestCallback) => {
      callback(0);
      return 1;
    });
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  test("initializes a mocked viewer, reports progress, signals readiness, and disposes on unmount", async () => {
    const onReady = vi.fn();
    const onProgress = vi.fn();

    viewerState.initialize.mockImplementation(async ({ onProgress }) => {
      onProgress?.({ loaded: 25, percent: 25, total: 100 });
    });
    const { unmount } = render(
      <VisualizeViewer onProgress={onProgress} onReady={onReady} />,
    );

    expect(screen.getByTestId("vsfx-visualize-viewer")).toBeInTheDocument();

    await waitFor(() => {
      expect(viewerState.initialize).toHaveBeenCalledTimes(1);
    });

    expect(onProgress).toHaveBeenCalledWith({ loaded: 25, percent: 25, total: 100 });

    await new Promise((resolve) => {
      setTimeout(resolve, 200);
    });

    await waitFor(() => {
      expect(onReady).toHaveBeenCalledWith(viewerState);
    });

    expect(viewerState.open).not.toHaveBeenCalled();

    unmount();

    await waitFor(() => {
      expect(viewerState.dispose).toHaveBeenCalledTimes(1);
    });
  });
});
