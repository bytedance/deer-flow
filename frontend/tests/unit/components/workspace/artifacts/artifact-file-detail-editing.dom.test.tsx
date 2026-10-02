import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { useState, type PropsWithChildren } from "react";

const mocks = rs.hoisted(() => ({
  artifactContent: {
    content: undefined as string | undefined,
    url: undefined as string | undefined,
    sha256: undefined as string | undefined,
    truncated: false,
    previewBytes: undefined as number | undefined,
    totalBytes: undefined as number | undefined,
    fullContentRequested: false,
    loadFullContent: rs.fn(),
    isLoading: false,
    error: undefined as unknown,
  },
  setSidebarOpen: rs.fn(),
}));

rs.mock("@/core/artifacts/hooks", () => ({
  useArtifactContent: () => mocks.artifactContent,
}));
rs.mock("@/components/workspace/messages/context", () => ({
  useThread: () => ({ thread: { isLoading: false }, isMock: false }),
}));
rs.mock("@/components/ui/sidebar", () => ({
  useSidebar: () => ({ setOpen: mocks.setSidebarOpen }),
}));
rs.mock("next/navigation", () => ({
  usePathname: () => "/workspace/chats/artifact-editing-test",
}));
rs.mock("@/core/auth/AuthProvider", () => ({
  useAuth: () => ({ user: null }),
}));
rs.mock("@/core/config", () => ({
  getBackendBaseURL: () => "/backend",
}));
rs.mock("@/env", () => ({
  env: { NEXT_PUBLIC_STATIC_WEBSITE_ONLY: "false" },
}));
rs.mock("@/core/api/fetcher", () => ({
  fetch: rs.fn(),
}));

// Exercise real React/provider state and editor callbacks without CodeMirror.
rs.mock("@/components/workspace/code-editor", () => ({
  CodeEditor: ({
    value,
    readonly,
    disabled,
    onChange,
  }: {
    value: string;
    readonly?: boolean;
    disabled?: boolean;
    onChange?: (value: string) => void;
  }) => (
    <textarea
      aria-label="Artifact source"
      value={value}
      readOnly={readonly}
      disabled={disabled}
      onChange={(event) => onChange?.(event.target.value)}
    />
  ),
}));

import { ArtifactFileDetail } from "@/components/workspace/artifacts/artifact-file-detail";
import { ArtifactsProvider } from "@/components/workspace/artifacts/context";
import { fetch as apiFetch } from "@/core/api/fetcher";
import { I18nProvider } from "@/core/i18n/context";

const filepath = "/mnt/user-data/outputs/large.txt";
const threadId = "artifact-editing-test";
const prefix = "a".repeat(1024 * 1024);
const fullContent = prefix + "\nComplete file tail\n";
const revision = "a".repeat(64);
const mockedFetch = rs.mocked(apiFetch);

function Wrapper({ children }: PropsWithChildren) {
  const [queryClient] = useState(
    () => new QueryClient({ defaultOptions: { queries: { retry: false } } }),
  );
  return (
    <QueryClientProvider client={queryClient}>
      <I18nProvider initialLocale="en-US">
        <ArtifactsProvider>{children}</ArtifactsProvider>
      </I18nProvider>
    </QueryClientProvider>
  );
}

function detail() {
  return <ArtifactFileDetail filepath={filepath} threadId={threadId} />;
}

function renderDetail() {
  // Let the provider restore thread state before the loaded detail mounts,
  // just as the real asynchronous artifact request does.
  const result = render(<div />, { wrapper: Wrapper });
  result.rerender(detail());
  return result;
}

function loadFull() {
  Object.assign(mocks.artifactContent, {
    content: fullContent,
    truncated: false,
    fullContentRequested: true,
  });
}

function source() {
  return screen.getByRole<HTMLTextAreaElement>("textbox", {
    name: "Artifact source",
  });
}

function save() {
  return screen.getByRole<HTMLButtonElement>("button", { name: "Save" });
}

beforeEach(() => {
  window.sessionStorage.clear();
  Object.assign(mocks.artifactContent, {
    content: prefix,
    sha256: revision,
    truncated: true,
    previewBytes: prefix.length,
    totalBytes: fullContent.length,
    fullContentRequested: false,
    isLoading: false,
    error: undefined,
  });
  mockedFetch.mockResolvedValue(
    new Response(
      JSON.stringify({
        path: filepath,
        sha256: "b".repeat(64),
        size: prefix.length,
      }),
      { headers: { "Content-Type": "application/json" } },
    ),
  );
});

afterEach(() => {
  cleanup();
  rs.restoreAllMocks();
  rs.clearAllMocks();
});

describe("ArtifactFileDetail complete editing baseline", () => {
  it.each([
    ["truncated preview", { content: prefix, truncated: true }],
    ["failed refetch", { error: new Error("Artifact refetch failed") }],
    ["loading", { content: undefined, isLoading: true }],
  ])(
    "keeps an exit available during %s without losing the draft",
    (_name, state) => {
      loadFull();
      const { rerender } = renderDetail();
      fireEvent.click(screen.getByRole("button", { name: "Edit" }));
      fireEvent.change(source(), { target: { value: "my retained draft" } });

      Object.assign(mocks.artifactContent, state);
      rerender(detail());
      const exit = screen.getByRole<HTMLButtonElement>("button", {
        name: "Exit editing",
      });
      expect(exit.disabled).toBe(false);
      expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
      expect(
        screen.queryByRole("button", { name: "Discard changes" }),
      ).toBeNull();
      fireEvent.click(exit);
      expect(screen.queryByRole("button", { name: "Exit editing" })).toBeNull();

      Object.assign(mocks.artifactContent, {
        error: undefined,
        isLoading: false,
      });
      loadFull();
      rerender(detail());
      expect(source().readOnly).toBe(true);
      fireEvent.click(screen.getByRole("button", { name: "Edit" }));
      expect(source().value).toBe("my retained draft");
      expect(save().disabled).toBe(false);
      expect(mockedFetch).not.toHaveBeenCalled();
    },
  );

  it("does not offer editing for a truncated preview with a full-file ETag", () => {
    renderDetail();

    expect(screen.queryByRole("button", { name: "Edit" })).toBeNull();
    expect(screen.queryByRole("textbox")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Load full file" }));
    expect(mocks.artifactContent.loadFullContent).toHaveBeenCalledOnce();
  });

  it("is clean after edits are reverted to the full original with the same ETag", () => {
    const { rerender } = renderDetail();
    loadFull();
    rerender(detail());
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    expect(source().value).toBe(fullContent);

    fireEvent.change(source(), { target: { value: fullContent + "edited" } });
    expect(save().disabled).toBe(false);
    fireEvent.change(source(), { target: { value: fullContent } });

    expect(save().disabled).toBe(true);
    expect(screen.queryByText("Unsaved")).toBeNull();
  });

  it("keeps a deleted tail removed and saves it against the full-file revision", async () => {
    const { rerender } = renderDetail();
    loadFull();
    rerender(detail());
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    fireEvent.change(source(), { target: { value: prefix } });

    expect(source().value.length).toBe(prefix.length);
    expect(save().disabled).toBe(false);
    fireEvent.click(save());
    await waitFor(() => {
      expect(mockedFetch).toHaveBeenCalledWith(
        expect.stringContaining("/artifacts/mnt/user-data/outputs/large.txt"),
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ content: prefix, expected_sha256: revision }),
        },
      );
    });
  });

  it.each(["small file", ""])(
    "allows complete initial content without an explicit full-load request: %j",
    (content) => {
      Object.assign(mocks.artifactContent, { content, truncated: false });
      renderDetail();
      fireEvent.click(screen.getByRole("button", { name: "Edit" }));
      expect(source().value).toBe(content);
      fireEvent.change(source(), { target: { value: content + "edit" } });
      expect(save().disabled).toBe(false);
      fireEvent.change(source(), { target: { value: content } });
      expect(save().disabled).toBe(true);
    },
  );

  it("preserves a dirty draft across a partial reload and detects a remote conflict", () => {
    loadFull();
    const { rerender } = renderDetail();
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    fireEvent.change(source(), { target: { value: "my draft" } });

    // Switching panels remounts the detail while its provider retains the draft.
    rerender(<div />);
    Object.assign(mocks.artifactContent, { content: prefix, truncated: true });
    rerender(detail());
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
    loadFull();
    rerender(detail());
    expect(source().value).toBe("my draft");
    expect(save().disabled).toBe(false);

    Object.assign(mocks.artifactContent, {
      content: fullContent + "remote change",
      sha256: "c".repeat(64),
    });
    rerender(detail());
    expect(source().value).toBe("my draft");
    expect(save().disabled).toBe(true);
    expect(screen.getByText("Changed remotely")).toBeTruthy();

    rs.spyOn(window, "confirm").mockReturnValue(true);
    fireEvent.click(screen.getByRole("button", { name: "Discard changes" }));
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    expect(source().value).toBe(fullContent + "remote change");
    expect(save().disabled).toBe(true);
    expect(screen.queryByText("Changed remotely")).toBeNull();
  });
});
