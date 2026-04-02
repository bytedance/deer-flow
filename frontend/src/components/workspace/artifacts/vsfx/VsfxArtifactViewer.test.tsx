import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { render, screen, waitFor } from "@/test/render";

import { VsfxArtifactViewer } from "./VsfxArtifactViewer";

const visualizeViewerSpy = vi.fn();

vi.mock("@/lib/vsfx-viewer/components/VisualizeViewer", () => ({
  VisualizeViewer: (props: { data: ArrayBuffer; filename: string }) => {
    visualizeViewerSpy(props);

    return (
      <div
        data-byte-length={props.data.byteLength}
        data-filename={props.filename}
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

describe("VsfxArtifactViewer", () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    fetchMock.mockReset();
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
      expect(screen.getByTestId("vsfx-visualize-viewer-mock")).toHaveAttribute(
        "data-filename",
        "widget.vsfx",
      );
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
      expect(screen.getByTestId("vsfx-visualize-viewer-mock")).toHaveAttribute(
        "data-filename",
        "second.vsfx",
      );
    });

    firstPrimary.resolve(createBinaryResponse([1, 2, 3]));

    await waitFor(() => {
      expect(screen.getByTestId("vsfx-visualize-viewer-mock")).toHaveAttribute(
        "data-filename",
        "second.vsfx",
      );
    });
  });
});
