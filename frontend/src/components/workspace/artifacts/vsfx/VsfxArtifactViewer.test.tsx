import { useEffect } from "react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { fireEvent, render, screen, waitFor } from "@/test/render";

import { VsfxArtifactViewer } from "./VsfxArtifactViewer";

const visualizeViewerSpy = vi.fn();
const openSpy = vi.fn();
const disposeSpy = vi.fn();
const onSpy = vi.fn(() => () => undefined);
const viewerMock = {
  dispose: disposeSpy,
  on: onSpy,
  open: openSpy,
};

vi.mock("@/lib/vsfx-viewer/components/VisualizeViewer", () => ({
  VisualizeViewer: ({ onReady }: { onReady?: (viewer: typeof viewerMock) => void }) => {
    visualizeViewerSpy({ onReady });

    useEffect(() => {
      onReady?.(viewerMock);
    }, [onReady]);

    return (
      <div
        data-testid="vsfx-visualize-viewer-mock"
      />
    );
  },
}));

function createDeferred<T>() {
  let reject!: (error?: unknown) => void;
  let resolve!: (value: T | PromiseLike<T>) => void;
  const promise = new Promise<T>((innerResolve, innerReject) => {
    reject = innerReject;
    resolve = innerResolve;
  });

  return {
    promise,
    resolve,
    reject,
  };
}

function createJsonResponse(payload: unknown, init?: ResponseInit) {
  return new Response(JSON.stringify(payload), {
    headers: { "Content-Type": "application/json" },
    status: 200,
    ...init,
  });
}

function createBinaryResponse(bytes: number[]) {
  return new Response(new Uint8Array(bytes), { status: 200 });
}

function readFetchInputUrl(input: Parameters<typeof fetch>[0]) {
  if (input instanceof Request) {
    return input.url;
  }

  if (input instanceof URL) {
    return input.toString();
  }

  return input;
}

function readTranslateOffset(transform: string) {
  const match = /^translate\((-?\d+)px, (-?\d+)px\)$/.exec(transform);

  if (!match) {
    return { x: 0, y: 0 };
  }

  return {
    x: Number(match[1]),
    y: Number(match[2]),
  };
}

function mockSuccessfulVsfxArtifactFetches(fetchMock: ReturnType<typeof vi.fn<typeof fetch>>) {
  fetchMock.mockImplementation(async (input) => {
    const url = readFetchInputUrl(input);

    if (url.endsWith("/artifacts/widget.cda.json")) {
      return createJsonResponse({
        nodes: [
          {
            children: [],
            handle: 42,
            name: "Bolt",
          },
        ],
      });
    }

    if (url.endsWith("/artifacts/widget.Properties.json")) {
      return createJsonResponse({
        byHandle: {
          42: {
            Name: "Bolt",
          },
        },
      });
    }

    if (url.endsWith("/artifacts/widget.vsfx")) {
      return createBinaryResponse([1, 2, 3, 4]);
    }

    throw new Error(`Unexpected fetch URL: ${url}`);
  });
}

describe("VsfxArtifactViewer", () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    fetchMock.mockReset();
    openSpy.mockReset();
    onSpy.mockReset();
    onSpy.mockImplementation(() => () => undefined);
    disposeSpy.mockReset();
    visualizeViewerSpy.mockClear();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test("renders a DeerFlow-local loading state before the VSFX viewer becomes ready", async () => {
    fetchMock.mockImplementation(async (input) => {
      const url = readFetchInputUrl(input);

      if (url.endsWith("/artifacts/widget.cda.json")) {
        return createJsonResponse({ nodes: [{ id: "root" }] });
      }

      if (url.endsWith("/artifacts/widget.Properties.json")) {
        return createJsonResponse({ parts: [{ handle: 1 }] });
      }

      if (url.endsWith("/artifacts/widget.vsfx")) {
        return createBinaryResponse([1, 2, 3, 4]);
      }

      throw new Error(`Unexpected fetch URL: ${url}`);
    });

    render(
      <VsfxArtifactViewer
        artifacts={[
          "/artifacts/widget.vsfx",
          "/artifacts/widget.cda.json",
          "/artifacts/widget.Properties.json",
        ]}
        filepath="/artifacts/widget.vsfx"
        threadId="thread-123"
      />,
    );

    expect(screen.getByTestId("vsfx-viewer-root")).toBeInTheDocument();
    expect(screen.getByTestId("vsfx-loading")).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByTestId("vsfx-visualize-viewer-mock")).toBeInTheDocument();
      expect(openSpy).toHaveBeenCalledWith({
        data: expect.any(ArrayBuffer),
        filename: "widget.vsfx",
      });
    });

    expect(screen.queryByTestId("vsfx-loading")).not.toBeInTheDocument();
    expect(screen.queryByTestId("vsfx-error")).not.toBeInTheDocument();
  });

  test("renders a DeerFlow-local primary error state when the VSFX asset cannot load", async () => {
    fetchMock.mockImplementation(async (input) => {
      const url = readFetchInputUrl(input);

      if (url.endsWith("/artifacts/widget.vsfx")) {
        return new Response("missing", { status: 500 });
      }

      throw new Error(`Unexpected fetch URL: ${url}`);
    });

    render(
      <VsfxArtifactViewer
        artifacts={["/artifacts/widget.vsfx"]}
        filepath="/artifacts/widget.vsfx"
        threadId="thread-123"
      />,
    );

    expect(screen.getByTestId("vsfx-loading")).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByTestId("vsfx-error")).toBeInTheDocument();
    });

    expect(screen.queryByTestId("vsfx-loading")).not.toBeInTheDocument();
    expect(screen.queryByTestId("vsfx-visualize-viewer-mock")).not.toBeInTheDocument();
  });

  test("ignores stale primary loads when artifacts switch quickly", async () => {
    const firstPrimary = createDeferred<Response>();

    fetchMock.mockImplementation((input) => {
      const url = readFetchInputUrl(input);

      if (url.endsWith("/artifacts/first.vsfx")) {
        return firstPrimary.promise;
      }

      if (url.endsWith("/artifacts/second.vsfx")) {
        return Promise.resolve(createBinaryResponse([9, 9, 9]));
      }

      throw new Error(`Unexpected fetch URL: ${url}`);
    });

    const { rerender } = render(
      <VsfxArtifactViewer
        artifacts={["/artifacts/first.vsfx"]}
        filepath="/artifacts/first.vsfx"
        threadId="thread-123"
      />,
    );

    rerender(
      <VsfxArtifactViewer
        artifacts={["/artifacts/second.vsfx"]}
        filepath="/artifacts/second.vsfx"
        threadId="thread-123"
      />,
    );

    await waitFor(() => {
      expect(screen.getByTestId("vsfx-visualize-viewer-mock")).toBeInTheDocument();
      expect(openSpy).toHaveBeenCalledWith({
        data: expect.any(ArrayBuffer),
        filename: "second.vsfx",
      });
    });

    firstPrimary.resolve(createBinaryResponse([1, 2, 3]));

    await waitFor(() => {
      expect(openSpy).toHaveBeenLastCalledWith({
        data: expect.any(ArrayBuffer),
        filename: "second.vsfx",
      });
    });
  });

  test("reopens when the same filepath resolves to new bytes", async () => {
    let primaryRequestCount = 0;

    fetchMock.mockImplementation(async (input) => {
      const url = readFetchInputUrl(input);

      if (url.endsWith("/artifacts/widget.vsfx")) {
        primaryRequestCount += 1;
        return primaryRequestCount === 1
          ? createBinaryResponse([1, 2, 3, 4])
          : createBinaryResponse([9, 8, 7, 6]);
      }

      throw new Error(`Unexpected fetch URL: ${url}`);
    });

    const { rerender } = render(
      <VsfxArtifactViewer
        artifacts={["/artifacts/widget.vsfx"]}
        filepath="/artifacts/widget.vsfx"
        threadId="thread-123"
      />,
    );

    await waitFor(() => {
      expect(openSpy).toHaveBeenNthCalledWith(1, {
        data: expect.any(ArrayBuffer),
        filename: "widget.vsfx",
      });
    });

    rerender(
      <VsfxArtifactViewer
        artifacts={["/artifacts/widget.vsfx"]}
        filepath="/artifacts/widget.vsfx"
        threadId="thread-456"
      />,
    );

    await waitFor(() => {
      expect(openSpy).toHaveBeenNthCalledWith(2, {
        data: expect.any(ArrayBuffer),
        filename: "widget.vsfx",
      });
    });
  });

  test("does not reload the artifact when rerendered with a new artifacts array containing the same paths", async () => {
    mockSuccessfulVsfxArtifactFetches(fetchMock);

    const { rerender } = render(
      <VsfxArtifactViewer
        artifacts={[
          "/artifacts/widget.vsfx",
          "/artifacts/widget.cda.json",
          "/artifacts/widget.Properties.json",
        ]}
        filepath="/artifacts/widget.vsfx"
        threadId="thread-123"
      />,
    );

    await waitFor(() => {
      expect(openSpy).toHaveBeenCalledTimes(1);
      expect(fetchMock).toHaveBeenCalledTimes(3);
    });

    rerender(
      <VsfxArtifactViewer
        artifacts={[
          "/artifacts/widget.vsfx",
          "/artifacts/widget.cda.json",
          "/artifacts/widget.Properties.json",
        ]}
        filepath="/artifacts/widget.vsfx"
        threadId="thread-123"
      />,
    );

    await waitFor(() => {
      expect(openSpy).toHaveBeenCalledTimes(1);
    });

    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  test("renders the construct tree and selected properties windows minimized by default, then restores and re-minimizes them", async () => {
    mockSuccessfulVsfxArtifactFetches(fetchMock);

    render(
      <VsfxArtifactViewer
        artifacts={[
          "/artifacts/widget.vsfx",
          "/artifacts/widget.cda.json",
          "/artifacts/widget.Properties.json",
        ]}
        filepath="/artifacts/widget.vsfx"
        threadId="thread-123"
      />,
    );

    const treeWindow = await screen.findByTestId("vsfx-tree-window");
    const propertiesWindow = screen.getByTestId("vsfx-properties-window");

    expect(screen.getByText("Construct tree")).toBeInTheDocument();
    expect(screen.getByText("Selected properties")).toBeInTheDocument();
    expect(screen.queryByText("Bolt")).not.toBeInTheDocument();
    expect(screen.queryByText("Select a part to inspect its properties.")).not.toBeInTheDocument();
    expect(treeWindow).toHaveAttribute("data-state", "minimized");
    expect(propertiesWindow).toHaveAttribute("data-state", "minimized");

    fireEvent.click(screen.getByRole("button", { name: "Restore Construct tree" }));

    await waitFor(() => {
      expect(treeWindow).toHaveAttribute("data-state", "expanded");
    });

    expect(treeWindow).toHaveClass("h-auto", "max-h-[calc(100%-2rem)]");
    expect(treeWindow).not.toHaveClass("h-[calc(100%-2rem)]", "max-h-[40rem]");

    expect(screen.getByRole("button", { name: "Hide Bolt" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Minimize Construct tree" }));

    await waitFor(() => {
      expect(treeWindow).toHaveAttribute("data-state", "minimized");
    });

    expect(screen.queryByRole("button", { name: "Hide Bolt" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Restore Selected properties" }));

    await waitFor(() => {
      expect(propertiesWindow).toHaveAttribute("data-state", "expanded");
    });

    expect(propertiesWindow).toHaveClass("h-auto", "max-h-[calc(100%-2rem)]");
    expect(propertiesWindow).not.toHaveClass("h-[calc(100%-2rem)]", "max-h-[40rem]");

    expect(screen.getByText("Select a part to inspect its properties.")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Minimize Selected properties" }));

    await waitFor(() => {
      expect(propertiesWindow).toHaveAttribute("data-state", "minimized");
    });

    expect(screen.queryByText("Select a part to inspect its properties.")).not.toBeInTheDocument();
  });

  test("drags floating windows by the title bar within the viewer container and ignores drag starts from the minimize button", async () => {
    mockSuccessfulVsfxArtifactFetches(fetchMock);

    render(
      <VsfxArtifactViewer
        artifacts={[
          "/artifacts/widget.vsfx",
          "/artifacts/widget.cda.json",
          "/artifacts/widget.Properties.json",
        ]}
        filepath="/artifacts/widget.vsfx"
        threadId="thread-123"
      />,
    );

    const viewerRoot = await screen.findByTestId("vsfx-viewer-root");
    const treeWindow = screen.getByTestId("vsfx-tree-window");

    Object.defineProperty(viewerRoot, "getBoundingClientRect", {
      configurable: true,
      value: () => new DOMRect(0, 0, 900, 700),
    });

    Object.defineProperty(treeWindow, "getBoundingClientRect", {
      configurable: true,
      value: () => {
        const { x, y } = readTranslateOffset(treeWindow.style.transform);

        return new DOMRect(16 + x, 16 + y, 320, 240);
      },
    });

    fireEvent.click(screen.getByRole("button", { name: "Restore Construct tree" }));

    await waitFor(() => {
      expect(treeWindow).toHaveAttribute("data-state", "expanded");
    });

    const treeTitleBar = screen.getByTestId("vsfx-tree-window-titlebar");

    fireEvent.mouseDown(treeTitleBar, { button: 0, clientX: 40, clientY: 40 });
    fireEvent.mouseMove(window, { clientX: 280, clientY: 220 });
    fireEvent.mouseMove(window, { clientX: 320, clientY: 260 });
    fireEvent.mouseUp(window);

    await waitFor(() => {
      expect(treeWindow.style.transform).toBe("translate(280px, 220px)");
    });

    const minimizeButton = screen.getByRole("button", { name: "Minimize Construct tree" });

    fireEvent.mouseDown(minimizeButton, { button: 0, clientX: 150, clientY: 30 });
    fireEvent.mouseMove(window, { clientX: 700, clientY: 500 });
    fireEvent.mouseUp(window);

    expect(treeWindow.style.transform).toBe("translate(280px, 220px)");
  });
});
