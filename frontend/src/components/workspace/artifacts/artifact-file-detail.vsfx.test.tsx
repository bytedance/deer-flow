import type { ReactNode } from "react";
import { beforeEach, describe, expect, test, vi } from "vitest";

import { fireEvent, render, screen } from "@/test/render";

import { ArtifactFileDetail } from "./artifact-file-detail";

const artifactContentMock = vi.fn();
const selectArtifactMock = vi.fn();
const setOpenMock = vi.fn();

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

vi.mock("./context", () => ({
  useArtifacts: () => ({
    artifacts: [
      "/artifacts/model.vsfx",
      "/artifacts/other.vsfx",
      "/artifacts/readme.md",
      "/artifacts/index.html",
      "/artifacts/example.ts",
      "/artifacts/manual.pdf",
    ],
    select: selectArtifactMock,
    setOpen: setOpenMock,
  }),
}));

vi.mock("@/components/ui/toggle-group", () => ({
  ToggleGroup: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  ToggleGroupItem: ({ value }: { value: string }) => <button type="button">{value}</button>,
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

const mockedVsfxViewer = vi.fn(
  ({ filepath }: { artifacts: string[]; filepath: string; threadId: string }) => (
    <div data-filepath={filepath} data-testid="vsfx-artifact-viewer" />
  ),
);

vi.mock("./vsfx/VsfxArtifactViewer", () => ({
  VsfxArtifactViewer: (props: { artifacts: string[]; filepath: string; threadId: string }) =>
    mockedVsfxViewer(props),
}));

vi.mock("@/components/workspace/artifacts/vsfx/VsfxArtifactViewer", () => ({
  VsfxArtifactViewer: (props: { artifacts: string[]; filepath: string; threadId: string }) =>
    mockedVsfxViewer(props),
}));

describe("ArtifactFileDetail VSFX integration", () => {
  beforeEach(() => {
    artifactContentMock.mockImplementation(({ filepath }: { filepath: string }) => ({
      content:
        filepath === "/artifacts/readme.md"
          ? "# VSFX notes"
          : filepath === "/artifacts/index.html"
            ? "<p>html preview</p>"
            : filepath === "/artifacts/example.ts"
              ? "export const answer = 42;"
              : null,
      url:
        filepath === "/artifacts/index.html"
          ? "/artifact/thread-123/artifacts/index.html"
          : undefined,
    }));
    mockedVsfxViewer.mockClear();
    selectArtifactMock.mockClear();
    setOpenMock.mockClear();
  });

  test("routes .vsfx artifacts into VsfxArtifactViewer and keeps shared artifact actions", () => {
    render(
      <ArtifactFileDetail filepath="/artifacts/model.vsfx" threadId="thread-123" />,
    );

    expect(screen.getByTestId("vsfx-artifact-viewer")).toHaveAttribute(
      "data-filepath",
      "/artifacts/model.vsfx",
    );
    expect(mockedVsfxViewer).toHaveBeenCalledWith(
      expect.objectContaining({
        artifacts: expect.arrayContaining(["/artifacts/model.vsfx", "/artifacts/other.vsfx"]),
        filepath: "/artifacts/model.vsfx",
        threadId: "thread-123",
      }),
    );

    expect(screen.getByRole("combobox", { name: "Artifact file" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "other.vsfx" }));
    expect(selectArtifactMock).toHaveBeenCalledWith("/artifacts/other.vsfx");

    expect(
      screen.getByRole("link", { name: /open in new window/i }),
    ).toHaveAttribute("href", "/artifact/thread-123/artifacts/model.vsfx");
    expect(screen.getByRole("link", { name: /download/i })).toHaveAttribute(
      "href",
      "/artifact/thread-123/artifacts/model.vsfx?download=true",
    );

    fireEvent.click(screen.getByRole("button", { name: /close/i }));
    expect(setOpenMock).toHaveBeenCalledWith(false);

    expect(screen.queryByRole("button", { name: /copy to clipboard/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "code" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "preview" })).not.toBeInTheDocument();
    expect(screen.queryByTestId("code-editor")).not.toBeInTheDocument();
  });

  test("keeps markdown html code and iframe branches unchanged", () => {
    const { rerender, container } = render(
      <ArtifactFileDetail filepath="/artifacts/readme.md" threadId="thread-123" />,
    );

    expect(screen.getByTestId("markdown-preview")).toHaveTextContent("# VSFX notes");
    expect(screen.getByRole("button", { name: "code" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "preview" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /copy to clipboard/i })).toBeInTheDocument();

    rerender(
      <ArtifactFileDetail filepath="/artifacts/index.html" threadId="thread-123" />,
    );

    const previewFrame = container.querySelector('iframe[title="Artifact preview"]');
    expect(previewFrame).not.toBeNull();
    expect(previewFrame).toHaveAttribute("src", "/artifact/thread-123/artifacts/index.html");

    rerender(
      <ArtifactFileDetail filepath="/artifacts/example.ts" threadId="thread-123" />,
    );

    expect(screen.getByTestId("code-editor")).toHaveAttribute(
      "data-value",
      "export const answer = 42;",
    );
    expect(screen.getByRole("button", { name: /copy to clipboard/i })).toBeInTheDocument();

    rerender(
      <ArtifactFileDetail filepath="/artifacts/manual.pdf" threadId="thread-123" />,
    );

    const fallbackFrame = container.querySelector(
      'iframe[src="/artifact/thread-123/artifacts/manual.pdf"]',
    );
    expect(fallbackFrame).not.toBeNull();
    expect(screen.queryByTestId("vsfx-artifact-viewer")).not.toBeInTheDocument();
  });
});
