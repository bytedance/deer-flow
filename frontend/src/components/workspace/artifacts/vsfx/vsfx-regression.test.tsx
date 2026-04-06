import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, test, vi } from "vitest";

import { fireEvent, render, screen, waitFor } from "@/test/render";

import { ArtifactFileDetail } from "../artifact-file-detail";

const artifactContentMock = vi.fn();
const selectArtifactMock = vi.fn();
const setOpenMock = vi.fn();

type MockViewerListenerMap = {
  clear: () => void;
  databasechunk: (payload: { data: ArrayBuffer; filename: string }) => void;
  geometryend: (payload: { filename: string }) => void;
  select: (handles: Array<string | number>) => void;
};

type MockViewerListener = (...args: unknown[]) => void;

class MockVsfxViewer {
  constructor(
    private readonly onOpen?: (payload: { data: ArrayBuffer; filename: string }) => void,
  ) {}

  readonly executeCommand = vi.fn((commandName: string, ...args: unknown[]) => {
    if (commandName === "clearSelected") {
      this.emit("clear");
    }

    if (commandName === "setSelected") {
      this.emit("select", (args[0] as Array<string | number> | undefined) ?? []);
    }
  });

  readonly setActiveDragger = vi.fn();

  private readonly listeners = new Map<keyof MockViewerListenerMap, Set<MockViewerListener>>();

  clearSlices() {
    void 0;
  }

  dispose() {
    void 0;
  }

  emit<TName extends keyof MockViewerListenerMap>(
    eventName: TName,
    ...args: Parameters<MockViewerListenerMap[TName]>
  ) {
    for (const listener of this.listeners.get(eventName) ?? []) {
      (listener as (...listenerArgs: Parameters<MockViewerListenerMap[TName]>) => void)(...args);
    }
  }

  getContainer() {
    return document.createElement("div");
  }

  getOptions() {
    return {};
  }

  getSelected() {
    return [];
  }

  on<TName extends keyof MockViewerListenerMap>(
    eventName: TName,
    listener: MockViewerListenerMap[TName],
  ) {
    const listeners = this.listeners.get(eventName) ?? new Set<MockViewerListener>();
    listeners.add(listener as unknown as MockViewerListener);
    this.listeners.set(eventName, listeners);

    return () => {
      listeners.delete(listener as unknown as MockViewerListener);
    };
  }

  open(payload?: { data: ArrayBuffer; filename: string }) {
    if (payload) {
      this.onOpen?.(payload);
      this.emit("databasechunk", payload);
      this.emit("geometryend", { filename: payload.filename });
    }

    return Promise.resolve();
  }

  render() {
    void 0;
  }

  resize() {
    void 0;
  }

  update() {
    void 0;
  }
}

function createDeferred<T>() {
  let reject!: (reason?: unknown) => void;
  let resolve!: (value: T | PromiseLike<T>) => void;
  const promise = new Promise<T>((innerResolve, innerReject) => {
    resolve = innerResolve;
    reject = innerReject;
  });

  return {
    promise,
    reject,
    resolve,
  };
}

function createJsonResponse(payload: unknown, init?: ResponseInit) {
  return new Response(JSON.stringify(payload), {
    headers: { "Content-Type": "application/json" },
    status: 200,
    ...init,
  });
}

function createTextResponse(payload: string, init?: ResponseInit) {
  return new Response(payload, {
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

let currentArtifacts = [
  "/artifacts/qa-smoke.vsfx",
  "/artifacts/qa-smoke.cda.json",
  "/artifacts/qa-smoke.properties.json",
  "/artifacts/control.md",
];
let currentViewer: MockVsfxViewer | null = null;

vi.mock("@/core/artifacts/hooks", () => ({
  useArtifactContent: (args: unknown) => artifactContentMock(args),
}));

vi.mock("@/components/workspace/messages/context", () => ({
  useThread: () => ({
    isMock: false,
    thread: {},
  }),
}));

vi.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({
    t: {
      clipboard: {
        copiedToClipboard: "Copied to clipboard",
        copyToClipboard: "Copy to clipboard",
      },
      common: {
        close: "Close",
        download: "Download",
        install: "Install",
        openInNewWindow: "Open in new window",
      },
      toolCalls: {
        skillInstallTooltip: "Install skill",
      },
    },
  }),
}));

vi.mock("@/core/artifacts/utils", () => ({
  normalizeArtifactFilepath: (filepath: string) => filepath,
  urlOfArtifact: ({
    download = false,
    filepath,
    threadId,
  }: {
    download?: boolean;
    filepath: string;
    threadId: string;
  }) => `/artifact/${threadId}${filepath}${download ? "?download=true" : ""}`,
}));

vi.mock("@/components/workspace/code-editor", () => ({
  CodeEditor: ({ value }: { value: string }) => (
    <div data-testid="code-editor" data-value={value} />
  ),
}));

vi.mock("streamdown", () => ({
  Streamdown: ({ children }: { children: string }) => (
    <div data-testid="markdown-preview">{children}</div>
  ),
}));

vi.mock("../context", () => ({
  useArtifacts: () => ({
    artifacts: currentArtifacts,
    select: selectArtifactMock,
    setOpen: setOpenMock,
  }),
}));

vi.mock("@/components/ui/select", () => {
  let currentValue = "";
  let onValueChange: ((value: string) => void) | undefined;

  return {
    Select: ({
      children,
      onValueChange: nextOnValueChange,
      value,
    }: {
      children: ReactNode;
      onValueChange?: (value: string) => void;
      value: string;
    }) => {
      currentValue = value;
      onValueChange = nextOnValueChange;

      return <div data-testid="artifact-select">{children}</div>;
    },
    SelectContent: ({ children }: { children: ReactNode }) => <div>{children}</div>,
    SelectGroup: ({ children }: { children: ReactNode }) => <div>{children}</div>,
    SelectItem: ({
      children,
      value,
    }: {
      children: ReactNode;
      value: string;
    }) => (
      <button type="button" onClick={() => onValueChange?.(value)}>
        {children}
      </button>
    ),
    SelectTrigger: ({ children }: { children: ReactNode }) => (
      <button
        aria-controls="artifact-file-options"
        aria-expanded="true"
        aria-label="Artifact file"
        role="combobox"
        type="button"
      >
        {children}
      </button>
    ),
    SelectValue: ({ placeholder }: { placeholder?: string }) => (
      <span>{currentValue.split("/").pop() ?? placeholder}</span>
    ),
  };
});

vi.mock("@/lib/vsfx-viewer/components/VisualizeViewer", () => ({
  VisualizeViewer: ({ onReady }: { onReady?: (viewer: MockVsfxViewer) => void }) => {
    const [openPayload, setOpenPayload] = useState<{ data: ArrayBuffer; filename: string } | null>(null);

    useEffect(() => {
      const viewer = new MockVsfxViewer((payload) => {
        setOpenPayload(payload);
      });
      currentViewer = viewer;
      onReady?.(viewer);

      return () => {
        if (currentViewer === viewer) {
          currentViewer = null;
        }
      };
    }, [onReady]);

    return (
      <div
        className="min-h-0 flex-1"
        data-byte-length={openPayload?.data.byteLength ?? 0}
        data-filename={openPayload?.filename ?? ""}
        data-testid="vsfx-canvas"
      />
    );
  },
}));

describe("VSFX regression coverage", () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    artifactContentMock.mockImplementation(({ filepath }: { filepath: string }) => ({
      content:
        filepath === "/artifacts/control.md"
          ? "# Control artifact"
          : filepath === "/artifacts/example.ts"
            ? "export const answer = 42;"
            : null,
      url: undefined,
    }));
    currentArtifacts = [
      "/artifacts/qa-smoke.vsfx",
      "/artifacts/qa-smoke.cda.json",
      "/artifacts/qa-smoke.properties.json",
      "/artifacts/control.md",
      "/artifacts/example.ts",
      "/artifacts/manual.pdf",
    ];
    currentViewer = null;
    fetchMock.mockReset();
    selectArtifactMock.mockClear();
    setOpenMock.mockClear();
    vi.stubGlobal("fetch", fetchMock);
  });

  test("renders integrated selectors, supports tree selection, and clears selection from the toolbar", async () => {
    fetchMock.mockImplementation(async (input) => {
      const url = readFetchInputUrl(input);

      if (url.endsWith("/artifacts/qa-smoke.cda.json")) {
        return createJsonResponse({
          nodes: [
            {
              children: [],
              handle: 42,
              name: "Portal beam",
            },
          ],
        });
      }

      if (url.endsWith("/artifacts/qa-smoke.properties.json")) {
        return createJsonResponse({
          byHandle: {
            42: {
              Name: "Portal beam",
              Material: {
                Grade: "S355",
              },
            },
          },
        });
      }

      if (url.endsWith("/artifacts/qa-smoke.vsfx")) {
        return createBinaryResponse([1, 2, 3, 4]);
      }

      throw new Error(`Unexpected fetch URL: ${url}`);
    });

    render(
      <div className="h-[480px] w-[360px]">
        <ArtifactFileDetail filepath="/artifacts/qa-smoke.vsfx" threadId="thread-123" />
      </div>,
    );

    expect(screen.getByTestId("vsfx-loading")).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByTestId("vsfx-viewer-root")).toBeInTheDocument();
      expect(screen.getByTestId("vsfx-toolbar")).toBeInTheDocument();
      expect(screen.getByTestId("vsfx-canvas")).toBeInTheDocument();
      expect(screen.getByTestId("vsfx-tree-window")).toBeInTheDocument();
      expect(screen.getByTestId("vsfx-properties-window")).toBeInTheDocument();
    });

    expect(screen.queryByTestId("vsfx-loading")).not.toBeInTheDocument();
    expect(screen.getByTestId("vsfx-toolbar")).toHaveClass("w-full", "flex-wrap");
    expect(screen.getByTestId("vsfx-viewer-root")).toHaveClass("overflow-hidden");

    fireEvent.click(screen.getByRole("button", { name: "Restore Construct tree" }));
    fireEvent.click(screen.getByRole("button", { name: "Restore Selected properties" }));

    const treeRow = await screen.findByTestId("vsfx-tree-row-42");

    fireEvent.click(treeRow);

    await waitFor(() => {
      expect(screen.getByTestId("vsfx-property-row-general-name")).toHaveTextContent("Portal beam");
    });

    expect(screen.getByTestId("vsfx-property-row-material-grade")).toHaveTextContent("S355");

    fireEvent.click(screen.getByRole("button", { name: "Unselect" }));

    await waitFor(() => {
      expect(screen.getByText("Select a part to inspect its properties.")).toBeInTheDocument();
    });
  });

  test("supports cad-web style array-based properties payloads when selecting from the tree", async () => {
    fetchMock.mockImplementation(async (input) => {
      const url = readFetchInputUrl(input);

      if (url.endsWith("/artifacts/qa-smoke.cda.json")) {
        return createJsonResponse({
          nodes: [
            {
              children: [],
              handle: 42,
              name: "Portal beam",
            },
          ],
        });
      }

      if (url.endsWith("/artifacts/qa-smoke.properties.json")) {
        return createJsonResponse([
          {
            handle: "0",
            Weight: "248571.485",
          },
          {
            handle: "42",
            Name: "Portal beam",
            Material: "S355",
          },
        ]);
      }

      if (url.endsWith("/artifacts/qa-smoke.vsfx")) {
        return createBinaryResponse([1, 2, 3, 4]);
      }

      throw new Error(`Unexpected fetch URL: ${url}`);
    });

    render(
      <div className="h-[480px] w-[360px]">
        <ArtifactFileDetail filepath="/artifacts/qa-smoke.vsfx" threadId="thread-123" />
      </div>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("vsfx-viewer-root")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: "Restore Construct tree" }));
    fireEvent.click(screen.getByRole("button", { name: "Restore Selected properties" }));
    fireEvent.click(await screen.findByTestId("vsfx-tree-row-42"));

    await waitFor(() => {
      expect(screen.getByText("Handle 42")).toBeInTheDocument();
    });

    expect(screen.getByTestId("vsfx-property-row-general-name")).toHaveTextContent("Portal beam");
    expect(screen.getByTestId("vsfx-property-row-general-material")).toHaveTextContent("S355");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  test("keeps missing sibling metadata scoped while the main VSFX canvas stays mounted", async () => {
    currentArtifacts = [
      "/artifacts/missing-props.vsfx",
      "/artifacts/missing-props.cda.json",
      "/artifacts/control.md",
    ];

    fetchMock.mockImplementation(async (input) => {
      const url = readFetchInputUrl(input);

      if (url.endsWith("/artifacts/missing-props.cda.json")) {
        return createJsonResponse({
          nodes: [
            {
              children: [],
              handle: 7,
              name: "Brace",
            },
          ],
        });
      }

      if (url.endsWith("/artifacts/missing-props.vsfx")) {
        return createBinaryResponse([7, 7, 7]);
      }

      throw new Error(`Unexpected fetch URL: ${url}`);
    });

    render(<ArtifactFileDetail filepath="/artifacts/missing-props.vsfx" threadId="thread-123" />);

    await waitFor(() => {
      expect(screen.getByTestId("vsfx-canvas")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: "Restore Construct tree" }));
    fireEvent.click(screen.getByRole("button", { name: "Restore Selected properties" }));
    fireEvent.click(screen.getByTestId("vsfx-tree-row-7"));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(
        "Missing properties artifact: /artifacts/missing-props.Properties.json",
      );
    });

    expect(screen.getByTestId("vsfx-tree-window")).toBeInTheDocument();
    expect(screen.getByTestId("vsfx-properties-window")).toBeInTheDocument();
  });

  test("keeps malformed sibling JSON local to the affected panel", async () => {
    currentArtifacts = [
      "/artifacts/bad-props.vsfx",
      "/artifacts/bad-props.cda.json",
      "/artifacts/bad-props.properties.json",
      "/artifacts/control.md",
    ];

    fetchMock.mockImplementation(async (input) => {
      const url = readFetchInputUrl(input);

      if (url.endsWith("/artifacts/bad-props.cda.json")) {
        return createJsonResponse({
          nodes: [
            {
              children: [],
              handle: 9,
              name: "Column",
            },
          ],
        });
      }

      if (url.endsWith("/artifacts/bad-props.properties.json")) {
        return createTextResponse("{ this is not valid json }");
      }

      if (url.endsWith("/artifacts/bad-props.vsfx")) {
        return createBinaryResponse([9, 9, 9]);
      }

      throw new Error(`Unexpected fetch URL: ${url}`);
    });

    render(<ArtifactFileDetail filepath="/artifacts/bad-props.vsfx" threadId="thread-123" />);

    await waitFor(() => {
      expect(screen.getByTestId("vsfx-canvas")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: "Restore Construct tree" }));
    fireEvent.click(screen.getByRole("button", { name: "Restore Selected properties" }));
    fireEvent.click(screen.getByTestId("vsfx-tree-row-9"));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(
        "Malformed properties JSON: /artifacts/bad-props.properties.json",
      );
    });

    expect(screen.getByTestId("vsfx-tree-window")).toBeInTheDocument();
    expect(screen.getByTestId("vsfx-properties-window")).toBeInTheDocument();
  });

  test("ignores stale artifact loads during fast switching", async () => {
    const firstPrimary = createDeferred<Response>();

    currentArtifacts = [
      "/artifacts/first.vsfx",
      "/artifacts/second.vsfx",
      "/artifacts/control.md",
    ];

    fetchMock.mockImplementation((input) => {
      const url = readFetchInputUrl(input);

      if (url.endsWith("/artifacts/first.vsfx")) {
        return firstPrimary.promise;
      }

      if (url.endsWith("/artifacts/second.vsfx")) {
        return Promise.resolve(createBinaryResponse([2, 2, 2]));
      }

      throw new Error(`Unexpected fetch URL: ${url}`);
    });

    const { rerender } = render(
      <ArtifactFileDetail filepath="/artifacts/first.vsfx" threadId="thread-123" />,
    );

    rerender(<ArtifactFileDetail filepath="/artifacts/second.vsfx" threadId="thread-123" />);

    await waitFor(() => {
      expect(screen.getByTestId("vsfx-canvas")).toHaveAttribute("data-filename", "second.vsfx");
    });

    firstPrimary.resolve(createBinaryResponse([1, 1, 1]));

    await waitFor(() => {
      expect(screen.getByTestId("vsfx-canvas")).toHaveAttribute("data-filename", "second.vsfx");
    });
  });

  test("preserves non-VSFX renderer branches", async () => {
    render(<ArtifactFileDetail filepath="/artifacts/control.md" threadId="thread-123" />);

    expect(screen.getByTestId("markdown-preview")).toHaveTextContent("# Control artifact");
    expect(screen.queryByTestId("vsfx-viewer-root")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "example.ts" }));
    expect(selectArtifactMock).toHaveBeenCalledWith("/artifacts/example.ts");
  });
});
