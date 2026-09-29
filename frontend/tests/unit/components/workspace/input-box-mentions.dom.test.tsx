import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import type { ReactNode } from "react";

import { PromptInputProvider } from "@/components/ai-elements/prompt-input";
import { InputBox } from "@/components/workspace/input-box";
import { ThreadContext } from "@/components/workspace/messages/context";
import { AuthProvider } from "@/core/auth/AuthProvider";
import { DEFAULT_LOCALE } from "@/core/i18n";
import { I18nProvider } from "@/core/i18n/context";

rs.mock("next/navigation", () => ({
  useRouter: () => ({ push: rs.fn(), replace: rs.fn(), refresh: rs.fn() }),
  usePathname: () => "/workspace",
  useSearchParams: () => new URLSearchParams(),
}));

rs.mock("@/core/models/hooks", () => ({
  useModels: () => ({
    models: [],
    tokenUsageEnabled: false,
    isLoading: false,
    isFetching: false,
    error: null,
    refetch: rs.fn(),
  }),
}));

rs.mock("@/core/skills/hooks", () => ({
  useSkills: () => ({
    skills: [
      {
        name: "research",
        description: "Research a topic",
        category: "general",
        license: "MIT",
        enabled: true,
        editable: false,
      },
    ],
    isLoading: false,
    error: null,
  }),
}));

// Each test gets its own thread id: the composer persists the selected skill in
// a debounced, thread-scoped draft, and a shared id would let the first test's
// selection land in the second test's storage key.
function renderComposer(
  threadId = "mentions-thread",
  onSubmit = rs.fn(),
  onPrepareThread = rs.fn(),
) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const tree: ReactNode = (
    <I18nProvider initialLocale={DEFAULT_LOCALE}>
      <QueryClientProvider client={queryClient}>
        <AuthProvider
          initialUser={{
            id: "user-1",
            email: "user@example.test",
            system_role: "user",
            needs_setup: false,
            oauth_provider: null,
          }}
        >
          <ThreadContext.Provider
            value={{ thread: { messages: [] } as never, isMock: true }}
          >
            <PromptInputProvider>
              <InputBox
                threadId={threadId}
                projectId="project-1"
                onSubmit={onSubmit}
                onPrepareThread={onPrepareThread}
                status="ready"
                context={{ mode: "flash" } as never}
              />
            </PromptInputProvider>
          </ThreadContext.Provider>
        </AuthProvider>
      </QueryClientProvider>
    </I18nProvider>
  );
  return render(tree);
}

const attach = rs.fn();
const capability = { enabled: true, maxReferences: 3, isLoading: false };
rs.mock("@/core/features/hooks", () => ({
  useConversationReferencesCapability: () => capability,
}));
rs.mock("@/core/projects/api", () => ({
  attachProjectDocument: (...args: unknown[]) => attach(...args),
}));
rs.mock("@/core/projects/hooks", () => ({
  useInfiniteProjectDocuments: () => ({
    data: {
      pages: [
        {
          documents: [
            {
              id: "doc-1",
              name: "report.pdf",
              size_bytes: 10,
              content_missing: false,
            },
          ],
        },
      ],
    },
    isPending: false,
  }),
}));
rs.mock("@/core/threads/hooks", () => ({
  useInfiniteThreads: () => ({
    data: {
      pages: [
        [
          {
            thread_id: "source-1",
            values: { title: "Writer brief" },
            metadata: { agent_name: "writer" },
          },
          ...[2, 3, 4].map((id) => ({
            thread_id: `source-${id}`,
            values: { title: `Brief ${id}` },
            metadata: {},
          })),
        ],
      ],
    },
    isPending: false,
  }),
}));

beforeEach(() => {
  capability.enabled = true;
  attach.mockReset();
  attach.mockResolvedValue({
    filename: "report.pdf",
    size_bytes: 10,
    virtual_path: "/mnt/user-data/uploads/report.pdf",
    artifact_url: "/artifact",
  });
});
afterEach(() => {
  cleanup();
  window.sessionStorage.clear();
  rs.restoreAllMocks();
});
function enterMention(
  container: HTMLElement,
  text: string,
  caret = text.length,
) {
  const input = container.querySelector("textarea");
  if (!input) {
    const editor = container.querySelector<HTMLElement>(
      '[contenteditable="true"]',
    )!;
    const node = document.createTextNode(" " + text);
    editor.append(node);
    const range = document.createRange();
    range.setStart(node, 1 + caret);
    range.collapse(true);
    window.getSelection()?.removeAllRanges();
    window.getSelection()?.addRange(range);
    fireEvent.input(editor);
    return editor as HTMLTextAreaElement;
  }
  fireEvent.focus(input);
  fireEvent.change(input, {
    target: { value: text, selectionStart: caret, selectionEnd: caret },
  });
  return input;
}

describe("unified composer mentions", () => {
  it("keeps a skill inline in the middle and sends its explicit activation metadata", async () => {
    const submit = rs.fn();
    const { container } = renderComposer("skill-mention", submit);
    const input = enterMention(container, "Use @res carefully", 8);
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() =>
      expect(screen.getByTestId("inline-skill-reference")).toBeTruthy(),
    );
    const editor = container.querySelector('[contenteditable="true"]')!;
    await waitFor(() =>
      expect(editor.textContent).toBe("Use ✦research  carefully"),
    );
    fireEvent.keyDown(editor, { key: "Enter" });
    await waitFor(() => expect(submit).toHaveBeenCalled());
    expect(submit.mock.calls[0]![0].text).toBe("Use @research  carefully");
    expect(submit.mock.calls[0]![1].additionalKwargs.skill_references).toEqual([
      "research",
    ]);
  });
  it("leaves emails and cancelled or composing queries as text", () => {
    const { container } = renderComposer();
    enterMention(container, "a@example.com");
    expect(screen.queryByTestId("mention-picker")).toBeNull();
    const input = enterMention(container, "@res");
    fireEvent.keyDown(input, { key: "Enter", keyCode: 229 });
    expect(input.value).toBe("@res");
    expect(screen.queryByRole("button", { name: "Remove skill" })).toBeNull();
    fireEvent.keyDown(input, { key: "Escape" });
    expect(screen.queryByTestId("mention-picker")).toBeNull();
    expect(input.value).toBe("@res");
  });
  it("prepares the project thread, attaches once, and sends the confirmed file", async () => {
    const submit = rs.fn();
    const prepare = rs.fn();
    const { container } = renderComposer("file-mention", submit, prepare);
    enterMention(container, "Read @report");
    fireEvent.click(screen.getByRole("option", { name: "report.pdf" }));
    await waitFor(() =>
      expect(screen.getByTestId("project-attachment-chip")).toBeTruthy(),
    );
    expect(prepare).toHaveBeenCalledTimes(1);
    expect(attach).toHaveBeenCalledWith("project-1", "doc-1", "file-mention");
    enterMention(container, "Read @report");
    fireEvent.click(screen.getByRole("option", { name: "report.pdf" }));
    expect(attach).toHaveBeenCalledTimes(1);
    fireEvent.submit(container.querySelector("form")!);
    await waitFor(() => expect(submit).toHaveBeenCalled());
    expect(submit.mock.calls[0]![1].additionalKwargs.files).toEqual([
      {
        filename: "report.pdf",
        size: 10,
        path: "/mnt/user-data/uploads/report.pdf",
        status: "uploaded",
      },
    ]);
  });
  it("keeps the query after an attachment error and permits retry", async () => {
    attach.mockRejectedValueOnce(new Error("offline"));
    const { container } = renderComposer();
    const input = enterMention(container, "Read @report");
    fireEvent.click(screen.getByRole("option", { name: "report.pdf" }));
    await waitFor(() =>
      expect(screen.getByRole("alert").textContent).toContain("Could not add"),
    );
    expect(input.value).toBe("Read @report");
    expect(screen.queryByTestId("project-attachment-chip")).toBeNull();
    fireEvent.click(screen.getByRole("option", { name: "report.pdf" }));
    await waitFor(() =>
      expect(screen.getByTestId("project-attachment-chip")).toBeTruthy(),
    );
  });
  it("persists a conversation reference with its draft and sends its ID and display metadata", async () => {
    const submit = rs.fn();
    const rendered = renderComposer("reference-draft", submit);
    enterMention(rendered.container, "Review @Writer");
    fireEvent.click(screen.getByRole("option", { name: "Writer brief" }));
    await waitFor(() =>
      expect(screen.getByTestId("conversation-reference-chip")).toBeTruthy(),
    );
    fireEvent(window, new Event("pagehide"));
    rendered.unmount();
    const { container } = renderComposer("reference-draft", submit);
    await waitFor(() =>
      expect(screen.getByTestId("conversation-reference-chip")).toBeTruthy(),
    );
    fireEvent.submit(container.querySelector("form")!);
    await waitFor(() => expect(submit).toHaveBeenCalled());
    expect(submit.mock.calls[0]![1].conversationReferences).toEqual([
      "source-1",
    ]);
    expect(
      submit.mock.calls[0]![1].additionalKwargs.conversation_references,
    ).toEqual([
      { thread_id: "source-1", title: "Writer brief", agent_name: "writer" },
    ]);
  });
  it("hides conversations when the deployment disables references", () => {
    capability.enabled = false;
    const { container } = renderComposer();
    enterMention(container, "@");
    expect(screen.queryByRole("option", { name: "Writer brief" })).toBeNull();
  });
  it("the attachment button opens the same picker", () => {
    renderComposer();
    fireEvent.click(screen.getByTestId("add-attachments-button"));
    expect(screen.getByTestId("mention-picker")).toBeTruthy();
    expect(screen.getByRole("option", { name: "Upload a file" })).toBeTruthy();
  });
  it("does not select upload automatically for an unknown query", () => {
    const { container } = renderComposer();
    enterMention(container, "@missing");
    const upload = screen.getByRole("option", { name: "Upload a file" });
    expect(upload.getAttribute("aria-selected")).toBe("false");
  });
  it("ignores late attachment completion after the composer is replaced", async () => {
    let finish!: (value: unknown) => void;
    attach.mockReturnValueOnce(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );
    const first = renderComposer("old-thread");
    enterMention(first.container, "Read @report");
    fireEvent.click(screen.getByRole("option", { name: "report.pdf" }));
    await waitFor(() => expect(attach).toHaveBeenCalled());
    first.unmount();
    const second = renderComposer("new-thread");
    enterMention(second.container, "Keep this draft");
    finish({
      filename: "report.pdf",
      size_bytes: 10,
      virtual_path: "/mnt/user-data/uploads/report.pdf",
      artifact_url: "/artifact",
    });
    await waitFor(() =>
      expect(second.container.querySelector("textarea")!.value).toBe(
        "Keep this draft",
      ),
    );
    expect(screen.queryByTestId("project-attachment-chip")).toBeNull();
  });

  it("enforces the conversation cap while allowing removal and reselection", () => {
    const { container } = renderComposer();
    for (const name of ["Writer brief", "Brief 2", "Brief 3"]) {
      enterMention(container, `Review @${name.split(" ")[0]}`);
      fireEvent.click(screen.getByRole("option", { name }));
    }
    enterMention(container, "Review @Brief");
    const fourth = screen.getByRole("option", { name: "Brief 4" });
    expect(fourth.hasAttribute("disabled")).toBe(true);
    screen.getAllByTestId("conversation-reference-chip")[0]!.remove();
    fireEvent.input(container.querySelector('[contenteditable="true"]')!);
    expect(
      screen.getByRole("option", { name: "Brief 4" }).hasAttribute("disabled"),
    ).toBe(false);
  });
});
