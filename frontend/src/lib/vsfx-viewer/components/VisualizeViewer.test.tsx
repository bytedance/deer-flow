import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { VisualizeViewer } from "@/lib/vsfx-viewer/components/VisualizeViewer";
import { render, screen, waitFor } from "@/test/render";

let currentResolvedTheme: "dark" | "light" = "light";

const viewerState = {
  dispose: vi.fn(),
  initialize: vi.fn(),
  on: vi.fn(),
  open: vi.fn(),
  setBackgroundColor: vi.fn(),
};

vi.mock("next-themes", () => ({
  useTheme: () => ({
    resolvedTheme: currentResolvedTheme,
  }),
}));

vi.mock("@/lib/vsfx-viewer/runtime/Viewer", () => ({
  Viewer: vi.fn().mockImplementation(() => viewerState),
}));

describe("VisualizeViewer", () => {
  beforeEach(() => {
    currentResolvedTheme = "light";
    viewerState.dispose.mockReset();
    viewerState.initialize.mockReset();
    viewerState.on.mockReset();
    viewerState.open.mockReset();
    viewerState.setBackgroundColor.mockReset();
    viewerState.on.mockImplementation(() => () => undefined);
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
    expect(viewerState.setBackgroundColor).toHaveBeenCalledWith(0xffffff);

    unmount();

    await waitFor(() => {
      expect(viewerState.dispose).toHaveBeenCalledTimes(1);
    });
  });

  test("re-applies the SDK background color when the resolved theme changes", async () => {
    viewerState.initialize.mockResolvedValue(undefined);

    const { rerender } = render(<VisualizeViewer />);

    await waitFor(() => {
      expect(viewerState.setBackgroundColor).toHaveBeenCalledWith(0xffffff);
    });

    currentResolvedTheme = "dark";
    rerender(<VisualizeViewer />);

    await waitFor(() => {
      expect(viewerState.setBackgroundColor).toHaveBeenLastCalledWith(0x18181b);
    });
  });

  test("does not reinitialize the viewer when parent rerenders with new callback identities", async () => {
    viewerState.initialize.mockResolvedValue(undefined);

    const firstOnReady = vi.fn();
    const firstOnProgress = vi.fn();
    const firstOnError = vi.fn();

    const { rerender } = render(
      <VisualizeViewer
        onError={firstOnError}
        onProgress={firstOnProgress}
        onReady={firstOnReady}
      />,
    );

    await waitFor(() => {
      expect(viewerState.initialize).toHaveBeenCalledTimes(1);
    });

    await new Promise((resolve) => {
      setTimeout(resolve, 0);
    });
    viewerState.dispose.mockClear();

    rerender(
      <VisualizeViewer
        onError={vi.fn()}
        onProgress={vi.fn()}
        onReady={vi.fn()}
      />,
    );

    await waitFor(() => {
      expect(viewerState.initialize).toHaveBeenCalledTimes(1);
    });

    expect(viewerState.dispose).not.toHaveBeenCalled();
  });

  test("re-applies the SDK background color after the viewer opens content", async () => {
    let openListener: (() => void) | undefined;

    viewerState.initialize.mockResolvedValue(undefined);
    viewerState.on.mockImplementation((eventName: string, listener: () => void) => {
      if (eventName === "open") {
        openListener = listener;
      }

      return () => undefined;
    });

    render(<VisualizeViewer />);

    await waitFor(() => {
      expect(viewerState.setBackgroundColor).toHaveBeenCalledWith(0xffffff);
    });

    viewerState.setBackgroundColor.mockClear();
    openListener?.();

    await waitFor(() => {
      expect(viewerState.setBackgroundColor).toHaveBeenCalledWith(0xffffff);
    });
  });
});
