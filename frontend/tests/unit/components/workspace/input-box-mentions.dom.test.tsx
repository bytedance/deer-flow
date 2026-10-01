import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import type { ComponentProps, ReactNode } from "react";

import { PromptInputProvider } from "@/components/ai-elements/prompt-input";
import { InputBox } from "@/components/workspace/input-box";
import { referenceToken } from "@/components/workspace/mentions/inline-references";
import { ThreadContext } from "@/components/workspace/messages/context";
import { AuthProvider } from "@/core/auth/AuthProvider";
import { DEFAULT_LOCALE } from "@/core/i18n";
import { I18nProvider } from "@/core/i18n/context";
import {
  buildComposerDraftKey,
  writeComposerDraft,
} from "@/core/threads/composer-draft";

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

const skillsQuery = {
  isLoading: false,
  error: null as Error | null,
  refetch: rs.fn(),
};
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
    ...skillsQuery,
  }),
}));

// Each test gets its own thread id: the composer persists the selected skill in
// a debounced, thread-scoped draft, and a shared id would let the first test's
// selection land in the second test's storage key.
function renderComposer(
  threadId = "mentions-thread",
  onSubmit = rs.fn(),
  onPrepareThread = rs.fn(),
  props: Partial<ComponentProps<typeof InputBox>> = {},
  isMock = true,
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
            value={{ thread: { messages: [] } as never, isMock }}
          >
            <PromptInputProvider>
              <InputBox
                threadId={threadId}
                projectId="project-1"
                onSubmit={onSubmit}
                onPrepareThread={onPrepareThread}
                status="ready"
                context={{ mode: "flash" } as never}
                {...props}
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
const capability = {
  enabled: true,
  maxReferences: 3,
  isLoading: false,
  isSuccess: true,
  error: null as Error | null,
  refetch: rs.fn(),
};
const polish = rs.fn();
rs.mock("@/core/input-polish/api", () => ({
  polishInputDraft: (...args: unknown[]) => polish(...args),
}));
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
  capability.maxReferences = 3;
  capability.isLoading = false;
  capability.isSuccess = true;
  capability.error = null;
  capability.refetch.mockReset();
  polish.mockReset();
  skillsQuery.isLoading = false;
  skillsQuery.error = null;
  skillsQuery.refetch.mockReset();
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

function saveDraft(threadId: string, text: string, extra = {}) {
  writeComposerDraft(
    window.sessionStorage,
    buildComposerDraftKey({
      userId: "user-1",
      agentName: null,
      threadId,
    }),
    { text, skillName: null, ...extra },
  );
}

describe("reference review regressions", () => {
  for (const entry of ["paste", "draft"] as const) {
    it(`resolves conversation tokens from ${entry} without another editor input`, async () => {
      const text =
        referenceToken("conversation", "source-1", "Writer brief") +
        " summarize";
      if (entry === "draft") saveDraft("raw-token", text);
      const submit = rs.fn();
      const { container } = renderComposer("raw-token", submit);
      if (entry === "paste") enterMention(container, text);
      await waitFor(() =>
        expect(screen.getByTestId("conversation-reference-chip")).toBeTruthy(),
      );
      fireEvent.submit(container.querySelector("form")!);
      await waitFor(() => expect(submit).toHaveBeenCalledTimes(1));
      expect(submit.mock.calls[0]![1].conversationReferences).toEqual([
        "source-1",
      ]);
      expect(
        submit.mock.calls[0]![1].additionalKwargs.conversation_references,
      ).toEqual([{ thread_id: "source-1", title: "Writer brief" }]);
    });
  }
  it("drops disabled restored context and renders its label as ordinary text", async () => {
    capability.enabled = false;
    saveDraft(
      "disabled-restore",
      referenceToken("conversation", "source-1", "Writer brief") + " summarize",
      {
        conversationReferences: [
          { threadId: "source-1", title: "Writer brief" },
        ],
      },
    );
    const submit = rs.fn();
    const { container } = renderComposer("disabled-restore", submit);
    await waitFor(() =>
      expect(screen.queryByTestId("conversation-reference-chip")).toBeNull(),
    );
    fireEvent.submit(container.querySelector("form")!);
    await waitFor(() => expect(submit).toHaveBeenCalled());
    expect(submit.mock.calls[0]![1].conversationReferences).toBeUndefined();
    expect(submit.mock.calls[0]![0].text).toContain("@Writer brief");
  });
  it("uses the current capability limit on paste, edits, and picker counts", async () => {
    capability.maxReferences = 4;
    const submit = rs.fn();
    const { container } = renderComposer("cap-four", submit);
    enterMention(
      container,
      [1, 2, 3, 4, 5]
        .map((id) =>
          referenceToken("conversation", `source-${id}`, `Brief ${id}`),
        )
        .join(" "),
    );
    await waitFor(() =>
      expect(screen.getAllByTestId("conversation-reference-chip")).toHaveLength(
        4,
      ),
    );
    const editor = container.querySelector('[contenteditable="true"]')!;
    fireEvent.input(editor);
    fireEvent.submit(container.querySelector("form")!);
    await waitFor(() => expect(submit).toHaveBeenCalled());
    expect(submit.mock.calls[0]![1].conversationReferences).toEqual([
      "source-1",
      "source-2",
      "source-3",
      "source-4",
    ]);
  });
  it("does not send while conversation capability is loading", async () => {
    capability.isLoading = true;
    capability.isSuccess = false;
    const submit = rs.fn();
    const { container } = renderComposer("cap-loading", submit);
    enterMention(
      container,
      referenceToken("conversation", "source-1", "Brief"),
    );
    fireEvent.submit(container.querySelector("form")!);
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(submit).not.toHaveBeenCalled();
  });
  it("rejects pasted skill batches over the cap without losing the draft", async () => {
    const submit = rs.fn();
    const { container } = renderComposer("skill-cap", submit);
    enterMention(
      container,
      Array.from({ length: 17 }, (_, i) =>
        referenceToken("skill", `skill-${i}`, `skill-${i}`),
      ).join(" "),
    );
    fireEvent.submit(container.querySelector("form")!);
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(submit).not.toHaveBeenCalled();
    expect(screen.getAllByTestId("inline-skill-reference")).toHaveLength(17);
  });
  it("toggles an already selected skill instead of inserting duplicate tokens", async () => {
    const { container } = renderComposer("toggle-skill");
    enterMention(container, "@res");
    fireEvent.click(
      screen.getByRole("option", { name: "research Research a topic" }),
    );
    enterMention(container, "@res");
    const option = screen.getByRole("option", {
      name: "research Research a topic",
    });
    expect(option.getAttribute("aria-selected")).toBe("true");
    fireEvent.click(option);
    await waitFor(() =>
      expect(screen.queryByTestId("inline-skill-reference")).toBeNull(),
    );
  });
  it("reports skills loading and retries a failed skills query", () => {
    skillsQuery.error = new Error("offline");
    renderComposer("skill-error");
    fireEvent.click(screen.getByTestId("mention-button"));
    expect(screen.getByRole("alert").textContent).toContain("Could not load");
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(skillsQuery.refetch).toHaveBeenCalledTimes(1);
  });
  it("exposes the keyboard highlight separately from actual selections", () => {
    const { container } = renderComposer("aria");
    const input = enterMention(container, "@res");
    const option = screen.getByRole("option", {
      name: "research Research a topic",
    });
    expect(option.getAttribute("aria-selected")).toBe("false");
    expect(option.id).not.toBe("");
    expect(input.getAttribute("aria-activedescendant")).toBe(option.id);
  });
  it("locks legacy skill removal until attachment migration settles", async () => {
    let finish!: (value: unknown) => void;
    attach.mockReturnValueOnce(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );
    saveDraft("new", "Read @report", { skillName: "research" });
    const materialized = rs.fn();
    const { container } = renderComposer("materialized", rs.fn(), rs.fn(), {
      draftThreadId: "new",
      onReferenceFileAttached: materialized,
    });
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Remove skill" })).toBeTruthy(),
    );
    fireEvent.click(screen.getByTestId("mention-button"));
    fireEvent.click(screen.getByRole("option", { name: "report.pdf" }));
    await waitFor(() => expect(attach).toHaveBeenCalled());
    const remove = screen.getByRole("button", { name: "Remove skill" });
    expect(remove.hasAttribute("disabled")).toBe(true);
    fireEvent.click(remove);
    finish({
      filename: "report.pdf",
      size_bytes: 10,
      virtual_path: "/mnt/user-data/uploads/report.pdf",
      artifact_url: "/artifact",
    });
    await waitFor(() => expect(materialized).toHaveBeenCalledTimes(1));
    expect(container.textContent).toContain("@research");
  });
});

it("announces a pending skills request in the picker", () => {
  skillsQuery.isLoading = true;
  renderComposer("skills-pending");
  fireEvent.click(screen.getByTestId("mention-button"));
  expect(screen.getByRole("listbox").getAttribute("aria-busy")).toBe("true");
  expect(screen.getByRole("status").textContent).toContain("Loading");
});

it("the picker search exposes its active option while selected state remains independent", () => {
  renderComposer("search-aria");
  fireEvent.click(screen.getByTestId("mention-button"));
  const search = screen.getByRole("combobox");
  const research = screen.getByRole("option", {
    name: "research Research a topic",
  });
  expect(search.getAttribute("aria-activedescendant")).toBe(research.id);
  expect(research.getAttribute("aria-selected")).toBe("false");
  fireEvent.keyDown(search, { key: "ArrowDown" });
  expect(search.getAttribute("aria-activedescendant")).toBe(
    screen.getByRole("option", { name: "report.pdf" }).id,
  );
  expect(research.getAttribute("aria-selected")).toBe("false");
});

it("pasted file labels never manufacture confirmed attachment context", async () => {
  const submit = rs.fn();
  const { container } = renderComposer("file-paste", submit);
  enterMention(
    container,
    referenceToken("file", "doc-1", "report.pdf") + " read",
  );
  fireEvent.submit(container.querySelector("form")!);
  await waitFor(() => expect(submit).toHaveBeenCalled());
  expect(submit.mock.calls[0]![1].additionalKwargs?.files).toBeUndefined();
  expect(attach).not.toHaveBeenCalled();
});

it("a capability rerender before send acceptance cannot revive the accepted draft", async () => {
  let accepted!: () => void;
  let release!: () => void;
  const pending = new Promise<void>((resolve) => {
    release = resolve;
  });
  const submit = rs.fn((_message, options) => {
    accepted = options.onSent;
    return pending;
  });
  const { container } = renderComposer("accepted-rerender", submit);
  enterMention(container, "Accepted task");
  fireEvent.submit(container.querySelector("form")!);
  await waitFor(() => expect(submit).toHaveBeenCalledTimes(1));
  // Opening the picker changes state without editing the submitted snapshot.
  fireEvent.click(screen.getByTestId("mention-button"));
  await waitFor(() =>
    expect(screen.getByTestId("mention-picker")).toBeTruthy(),
  );
  accepted();
  fireEvent(window, new Event("pagehide"));
  expect(Object.values(window.sessionStorage).join("\n")).not.toContain(
    "Accepted task",
  );
  release();
});

describe("reference discovery failures and polish round trips", () => {
  it("preserves restored references and blocks sending until capability retry succeeds", async () => {
    capability.enabled = false;
    capability.maxReferences = 0;
    capability.isSuccess = false;
    capability.error = new Error("503 temporary");
    const token = referenceToken("conversation", "source-1", "Writer brief");
    const text = token + " summarize";
    saveDraft("cap-error", text, {
      conversationReferences: [
        { threadId: "source-1", title: "Writer brief", agentName: "writer" },
      ],
    });
    const submit = rs.fn();
    const { container } = renderComposer("cap-error", submit);
    await waitFor(() =>
      expect(screen.getByTestId("conversation-reference-chip")).toBeTruthy(),
    );
    fireEvent.submit(container.querySelector("form")!);
    await new Promise((resolve) => setTimeout(resolve, 400));
    expect(submit).not.toHaveBeenCalled();
    const key = buildComposerDraftKey({
      userId: "user-1",
      agentName: null,
      threadId: "cap-error",
    });
    expect(JSON.parse(window.sessionStorage.getItem(key)!).text).toBe(text);
    expect(
      JSON.parse(window.sessionStorage.getItem(key)!).conversationReferences,
    ).toEqual([
      { threadId: "source-1", title: "Writer brief", agentName: "writer" },
    ]);
    capability.refetch.mockImplementation(() => {
      capability.isSuccess = true;
      capability.enabled = true;
      capability.maxReferences = 3;
      capability.error = null;
    });
    fireEvent.click(screen.getByTestId("retry-conversation-capability"));
    expect(capability.refetch).toHaveBeenCalledTimes(1);
    // An ordinary editor update observes the recovered mock capability.
    enterMention(container, " now");
    fireEvent.submit(container.querySelector("form")!);
    await waitFor(() => expect(submit).toHaveBeenCalledTimes(1));
    expect(submit.mock.calls[0]![1].conversationReferences).toEqual([
      "source-1",
    ]);
    expect(
      submit.mock.calls[0]![1].additionalKwargs.conversation_references[0]
        .agent_name,
    ).toBe("writer");
  });

  it("offers capability retry from the picker without a selected conversation", async () => {
    capability.enabled = false;
    capability.isSuccess = false;
    capability.error = new Error("503 temporary");
    renderComposer("picker-cap-error");
    fireEvent.click(screen.getByTestId("mention-button"));
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(capability.refetch).toHaveBeenCalledTimes(1);
  });

  it("restores reordered overlapping skill labels in the intended positions and supports undo", async () => {
    const short = referenceToken("skill", "research", "research");
    const long = referenceToken("skill", "research-tools", "research-tools");
    const original = `Use ${short} after ${long}`;
    saveDraft("polish-prefix", original);
    polish.mockResolvedValue({
      rewritten_text: "Use @research-tools first, then @research.",
      changed: true,
    });
    const submit = rs.fn();
    const { container } = renderComposer(
      "polish-prefix",
      submit,
      rs.fn(),
      {},
      false,
    );
    await waitFor(() =>
      expect(screen.getAllByTestId("inline-skill-reference")).toHaveLength(2),
    );
    fireEvent.click(screen.getByTestId("polish-input-button"));
    await waitFor(() =>
      expect(
        container.querySelector('[contenteditable="true"]')?.textContent,
      ).toBe("Use ✦research-tools first, then ✦research."),
    );
    expect(
      screen
        .getAllByTestId("inline-skill-reference")
        .map((el) => el.dataset.reference),
    ).toEqual([long, short]);
    fireEvent.click(screen.getByTestId("polish-input-button"));
    await waitFor(() =>
      expect(
        screen
          .getAllByTestId("inline-skill-reference")
          .map((el) => el.dataset.reference),
      ).toEqual([short, long]),
    );
    fireEvent.click(screen.getByTestId("polish-input-button"));
    await waitFor(() =>
      expect(
        screen
          .getAllByTestId("inline-skill-reference")
          .map((el) => el.dataset.reference),
      ).toEqual([long, short]),
    );
    fireEvent.submit(container.querySelector("form")!);
    await waitFor(() => expect(submit).toHaveBeenCalledTimes(1));
    expect(submit.mock.calls[0]![0].text).toBe(
      "Use @research-tools first, then @research.",
    );
    expect(submit.mock.calls[0]![1].additionalKwargs.skill_references).toEqual([
      "research-tools",
      "research",
    ]);
  });
});
