import type { Message } from "@langchain/langgraph-sdk";
import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";

import { SidebarProvider } from "@/components/ui/sidebar";
import { ArtifactsProvider } from "@/components/workspace/artifacts/context";
import { MessageListItem } from "@/components/workspace/messages/message-list-item";
import { ArtifactDraftsProvider } from "@/core/artifacts/draft-context";
import { I18nContext } from "@/core/i18n/context";
import { enUS } from "@/core/i18n/locales/en-US";
import { zhCN } from "@/core/i18n/locales/zh-CN";
import * as messageUtils from "@/core/messages/utils";
import { useSkills } from "@/core/skills/hooks";

const installState = rs.hoisted(() => ({
  user: null as { id: string; system_role: string } | null,
  success: rs.fn(),
  error: rs.fn(),
}));

rs.mock("@/core/auth/AuthProvider", () => ({
  useAuth: () => ({ user: installState.user }),
}));
rs.mock("next/navigation", () => ({
  usePathname: () => "/workspace/chats/thread-1",
}));
rs.mock("sonner", () => ({
  toast: { success: installState.success, error: installState.error },
}));

// The unit under test is the row's copy-data memo, not message rendering.
// Stubbing the markdown pipeline also removes its first-render suspension:
// when a settled body suspends, React restarts the render attempt and
// legitimately re-runs useMemo factories, which would make call counts
// depend on microtask timing instead of the memo's own deps.
rs.mock("@/components/workspace/messages/markdown-content", () => ({
  MarkdownContent: () => null,
}));

// Count calls to the copy-data derivation itself. The render path reads the
// message content for the body (markdown, reasoning, tasks), so content
// getters cannot distinguish rendering reads from copy derivation — the spy
// on the derived entry point can.
const copyDataCalls = rs.spyOn(messageUtils, "getMessageCopyData");

function makeMessage(type: "human" | "ai"): Message {
  return {
    id: `${type}-1`,
    type,
    content: "copy me",
  } as unknown as Message;
}

function withI18n(ui: React.ReactElement) {
  return (
    <I18nContext.Provider
      value={{ locale: "en-US", setLocale: () => undefined, t: enUS }}
    >
      {ui}
    </I18nContext.Provider>
  );
}

function renderRow(
  message: Message,
  {
    showCopyButton,
    isLoading = false,
  }: { showCopyButton: boolean; isLoading?: boolean },
) {
  return render(
    withI18n(
      <MessageListItem
        message={message}
        threadId="thread-1"
        showCopyButton={showCopyButton}
        isLoading={isLoading}
      />,
    ),
  );
}

afterEach(cleanup);
afterEach(() => {
  copyDataCalls.mockClear();
});

describe("MessageListItem edit shortcuts during IME composition", () => {
  function openEditor() {
    const onEditAndRegenerate = rs.fn(async () => true);
    const view = render(
      withI18n(
        <MessageListItem
          message={makeMessage("human")}
          threadId="thread-1"
          canEdit
          onEditAndRegenerate={onEditAndRegenerate}
        />,
      ),
    );
    fireEvent.click(
      view.getByRole("button", { name: enUS.common.editAndRerun }),
    );
    const editor = view.getByRole("textbox");
    fireEvent.change(editor, { target: { value: "unfinished draft" } });
    return { view, editor, onEditAndRegenerate };
  }

  it.each([
    { key: "Escape", isComposing: true },
    { key: "Escape", keyCode: 229 },
    { key: "Enter", ctrlKey: true, isComposing: true },
    { key: "Enter", ctrlKey: true, keyCode: 229 },
    { key: "Enter", metaKey: true, isComposing: true },
    { key: "Enter", metaKey: true, keyCode: 229 },
  ])("leaves the draft and composing key untouched: %j", async (event) => {
    const { view, editor, onEditAndRegenerate } = openEditor();
    await act(async () => {
      expect(fireEvent.keyDown(editor, event)).toBe(true);
    });
    expect(view.getByRole("textbox")).toBe(editor);
    expect(view.getByDisplayValue("unfinished draft")).toBe(editor);
    expect(onEditAndRegenerate).not.toHaveBeenCalled();
  });

  it("still cancels with Escape outside composition", () => {
    const { view, editor, onEditAndRegenerate } = openEditor();
    fireEvent.keyDown(editor, { key: "Escape" });
    expect(view.queryByRole("textbox")).toBeNull();
    expect(onEditAndRegenerate).not.toHaveBeenCalled();
  });

  it.each([{ ctrlKey: true }, { metaKey: true }])(
    "still submits with modified Enter outside composition: %j",
    async (modifier) => {
      const { view, editor, onEditAndRegenerate } = openEditor();
      await act(async () => {
        fireEvent.keyDown(editor, { key: "Enter", ...modifier });
      });
      expect(onEditAndRegenerate).toHaveBeenCalledExactlyOnceWith(
        "unfinished draft",
      );
      expect(view.queryByRole("textbox")).toBeNull();
    },
  );
});

describe("MessageListItem copy-data derivation guard", () => {
  it("derives no copy data for an assistant row that never renders the toolbar", () => {
    const message = makeMessage("ai");

    const view = renderRow(message, { showCopyButton: false });
    expect(copyDataCalls).toHaveBeenCalledTimes(0);

    // The sole call site passes showCopyButton only for non-assistant rows;
    // the memo must stay gated so settled assistant rows skip the derivation
    // entirely (the pre-memo call sat behind the same toolbar guard).
    view.rerender(
      withI18n(
        <MessageListItem
          message={message}
          threadId="thread-1"
          showCopyButton={false}
          isLoading={false}
        />,
      ),
    );
    expect(copyDataCalls).toHaveBeenCalledTimes(0);
  });

  it("derives a human row's copy data once and reuses it across re-renders", () => {
    const message = makeMessage("human");

    const view = renderRow(message, { showCopyButton: true });
    // One memo serves both editing and the toolbar — not one derivation per
    // consumer.
    expect(copyDataCalls).toHaveBeenCalledTimes(1);

    view.rerender(
      withI18n(
        <MessageListItem
          message={message}
          threadId="thread-1"
          showCopyButton={true}
          isLoading={false}
        />,
      ),
    );
    expect(copyDataCalls).toHaveBeenCalledTimes(1);
  });

  it("still derives for a human row while loading (editing needs it)", () => {
    const message = makeMessage("human");

    renderRow(message, { showCopyButton: true, isLoading: true });

    expect(copyDataCalls.mock.calls.length).toBeGreaterThan(0);
  });
});

describe("MessageListItem conversation reference chip", () => {
  it.each([
    ["en-US", enUS, "Untitled"],
    ["zh-CN", zhCN, "未命名"],
  ] as const)(
    "names an untitled referenced chat in the UI language (%s)",
    (locale, t, expected) => {
      const message = {
        id: "human-ref",
        type: "human",
        content: "compare these",
        additional_kwargs: {
          conversation_references: [{ thread_id: "thread-2", title: "" }],
        },
      } as unknown as Message;
      const view = render(
        <I18nContext.Provider value={{ locale, setLocale: () => undefined, t }}>
          <MessageListItem
            message={message}
            threadId="thread-1"
            showCopyButton={false}
            isLoading={false}
          />
        </I18nContext.Provider>,
      );
      const chips = view.getByTestId("message-conversation-references");
      expect(chips.textContent).toBe(expected);
    },
  );
});

describe("MessageListItem edit lock while a goal is set", () => {
  function renderHumanRow(
    flags: { canEdit?: boolean; editLockedByGoal?: boolean },
    locale: "en-US" | "zh-CN" = "en-US",
  ) {
    return render(
      <I18nContext.Provider
        value={{
          locale,
          setLocale: () => undefined,
          t: locale === "en-US" ? enUS : zhCN,
        }}
      >
        <MessageListItem
          message={makeMessage("human")}
          threadId="thread-1"
          showCopyButton
          onEditAndRegenerate={async () => true}
          {...flags}
        />
      </I18nContext.Provider>,
    );
  }

  it("shows a locked pencil that explains itself and opens no editor", async () => {
    const view = renderHumanRow({ editLockedByGoal: true });
    const pencil = screen.getByRole("button", { name: "Edit and rerun" });
    expect(pencil.getAttribute("aria-disabled")).toBe("true");
    // Only the icon is dimmed, so the keyboard focus ring keeps full contrast.
    expect(pencil.className.split(" ")).not.toContain(
      "aria-disabled:opacity-50",
    );
    expect(pencil.querySelector("svg")?.getAttribute("class")).toContain(
      "opacity-50",
    );
    const description = document.getElementById(
      pencil.getAttribute("aria-describedby")!,
    );
    expect(description?.textContent).toBe(
      "Editing is off while a goal is set. Run /goal clear to edit.",
    );

    fireEvent.click(pencil);
    expect(view.container.querySelector("textarea")).toBeNull();

    // The tooltip opens on keyboard focus, and the toolbar shows while focus
    // is inside it, so the locked pencil is visible to keyboard users.
    await act(async () => {
      pencil.focus();
    });
    expect(
      (await screen.findAllByText(enUS.inputBox.goalBar.editLocked)).length,
    ).toBeGreaterThan(1);
    expect(screen.getByTestId("message-toolbar").className).toContain(
      "focus-within:opacity-100",
    );
  });

  it("explains the lock in zh-CN", () => {
    renderHumanRow({ editLockedByGoal: true }, "zh-CN");
    const pencil = screen.getByRole("button", { name: "编辑并重新运行" });
    expect(
      document.getElementById(pencil.getAttribute("aria-describedby")!)
        ?.textContent,
    ).toBe("设置了目标时不能编辑，先运行 /goal clear 清除目标。");
  });

  it("keeps the normal pencil when edit is allowed", () => {
    const view = renderHumanRow({ canEdit: true });
    const pencil = screen.getByRole("button", { name: "Edit and rerun" });
    expect(pencil.hasAttribute("aria-disabled")).toBe(false);
    fireEvent.click(pencil);
    expect(view.container.querySelector("textarea")).not.toBeNull();
  });

  it("renders no pencil when neither flag is set", () => {
    renderHumanRow({});
    expect(screen.queryByRole("button", { name: "Edit and rerun" })).toBeNull();
  });
});

describe("uploaded Skill archive installation", () => {
  const archive = {
    filename: "分析.skill",
    size: 512,
    path: "/mnt/user-data/uploads/分析.skill",
    status: "uploaded" as const,
  };

  const queryClients: QueryClient[] = [];

  function renderMessage(
    message: Message,
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false, gcTime: Infinity } },
    }),
    children?: React.ReactNode,
  ) {
    queryClients.push(queryClient);
    return render(
      withI18n(
        <QueryClientProvider client={queryClient}>
          <ArtifactDraftsProvider>
            <SidebarProvider>
              <ArtifactsProvider>
                <MessageListItem
                  message={message}
                  threadId="thread-1"
                  showCopyButton={false}
                />
                {children}
              </ArtifactsProvider>
            </SidebarProvider>
          </ArtifactDraftsProvider>
        </QueryClientProvider>,
      ),
    );
  }

  function renderArchive(file: messageUtils.FileInMessage = archive) {
    return renderMessage({
      ...makeMessage("human"),
      additional_kwargs: { files: [file] },
    } as unknown as Message);
  }

  function AvailableSkills() {
    const { skills } = useSkills();
    return (
      <output data-testid="available-skills">
        {skills.map((skill) => skill.name).join(",")}
      </output>
    );
  }

  afterEach(() => {
    for (const client of queryClients) client.clear();
    queryClients.length = 0;
    installState.user = null;
    installState.success.mockClear();
    installState.error.mockClear();
    rs.restoreAllMocks();
  });

  it("installs the original uploaded path only after an admin clicks", async () => {
    installState.user = { id: "admin", system_role: "admin" };
    const fetch = rs.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          success: true,
          skill_name: "analysis",
          message: "Installed analysis",
        }),
        { headers: { "Content-Type": "application/json" } },
      ),
    );
    renderArchive();
    expect(fetch).not.toHaveBeenCalled();
    fireEvent.click(
      screen.getByRole("button", { name: `Install ${archive.filename}` }),
    );
    await waitFor(() =>
      expect(installState.success).toHaveBeenCalledWith("Installed analysis"),
    );
    expect(fetch).toHaveBeenCalledTimes(1);
    const [url, init] = fetch.mock.calls[0]!;
    expect(url).toEqual(expect.stringContaining("/api/skills/install"));
    expect(init?.method).toBe("POST");
    expect(init?.credentials).toBe("include");
    expect(JSON.parse(init?.body as string)).toEqual({
      thread_id: "thread-1",
      path: archive.path,
    });
  });

  it.each([null, { id: "reader", system_role: "user" }])(
    "does not offer installation to %j",
    (user) => {
      installState.user = user;
      renderArchive();
      expect(
        screen.queryByRole("button", { name: `Install ${archive.filename}` }),
      ).toBeNull();
    },
  );

  it.each([
    { ...archive, filename: "notes.zip" },
    { ...archive, status: "uploading" as const },
    { ...archive, status: undefined },
    { ...archive, path: "" },
  ])(
    "does not install an ordinary, pending, or unavailable attachment: %j",
    (file) => {
      installState.user = { id: "admin", system_role: "admin" };
      renderArchive(file);
      expect(screen.queryByRole("button", { name: /^Install / })).toBeNull();
    },
  );

  it("keeps one request in flight and allows a retry after a rejected archive", async () => {
    installState.user = { id: "admin", system_role: "admin" };
    let finish!: (response: Response) => void;
    const fetch = rs.spyOn(globalThis, "fetch").mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    renderArchive();
    const button = screen.getByRole("button", {
      name: `Install ${archive.filename}`,
    });
    fireEvent.click(button);
    fireEvent.click(button);
    expect(fetch).toHaveBeenCalledTimes(1);
    expect((button as HTMLButtonElement).disabled).toBe(true);
    await act(async () =>
      finish(
        new Response(
          JSON.stringify({ detail: "Archive rejected by security review" }),
          { status: 400 },
        ),
      ),
    );
    await waitFor(() =>
      expect(installState.error).toHaveBeenCalledWith(
        "Archive rejected by security review",
      ),
    );
    expect((button as HTMLButtonElement).disabled).toBe(false);
    expect(installState.success).not.toHaveBeenCalled();
    fireEvent.click(button);
    expect(fetch).toHaveBeenCalledTimes(2);
    await act(async () =>
      finish(
        new Response(
          JSON.stringify({
            success: true,
            skill_name: "analysis",
            message: "Installed analysis",
          }),
        ),
      ),
    );
  });

  it.each(["current_uploads", "uploaded_files"])(
    "keeps %s text-derived attachments preview-only",
    (tag) => {
      installState.user = { id: "admin", system_role: "admin" };
      const fetch = rs.spyOn(globalThis, "fetch");
      renderMessage({
        ...makeMessage("human"),
        content: `<${tag}>\n- ${archive.filename} (512 B)\n  Path: ${archive.path}\n</${tag}>`,
      } as Message);
      const preview = screen.getByRole("button", {
        name: `${archive.filename} SKILL · 0.5 KB`,
      });
      expect(preview).toBeDefined();
      expect(
        screen.queryByRole("button", { name: `Install ${archive.filename}` }),
      ).toBeNull();
      fireEvent.click(preview);
      expect(fetch).not.toHaveBeenCalled();
    },
  );

  it("does not install an assistant attachment even with completed upload metadata", () => {
    installState.user = { id: "admin", system_role: "admin" };
    renderMessage({
      ...makeMessage("ai"),
      additional_kwargs: { files: [archive] },
    } as unknown as Message);
    expect(
      screen.getByRole("button", {
        name: `${archive.filename} SKILL · 0.5 KB`,
      }),
    ).toBeDefined();
    expect(
      screen.queryByRole("button", { name: `Install ${archive.filename}` }),
    ).toBeNull();
  });

  it("refreshes a mounted skills consumer only after a successful installation", async () => {
    installState.user = { id: "admin", system_role: "admin" };
    let installed = false;
    let reads = 0;
    const fetch = rs
      .spyOn(globalThis, "fetch")
      .mockImplementation(async (_url, init) => {
        if (init?.method === "POST") {
          installed = true;
          return new Response(
            JSON.stringify({
              success: true,
              skill_name: "analysis",
              message: "Installed analysis",
            }),
          );
        }
        reads++;
        return new Response(
          JSON.stringify({
            skills: installed
              ? [
                  {
                    name: "analysis",
                    description: "Uploaded analysis skill",
                    category: "custom",
                    license: "MIT",
                    enabled: true,
                    editable: true,
                  },
                ]
              : [],
          }),
        );
      });
    renderMessage(
      {
        ...makeMessage("human"),
        additional_kwargs: { files: [archive] },
      } as unknown as Message,
      undefined,
      <AvailableSkills />,
    );
    await waitFor(() => expect(reads).toBe(1));
    expect(screen.getByTestId("available-skills").textContent).toBe("");
    fireEvent.click(
      screen.getByRole("button", { name: `Install ${archive.filename}` }),
    );
    await waitFor(() =>
      expect(screen.getByTestId("available-skills").textContent).toBe(
        "analysis",
      ),
    );
    expect(reads).toBe(2);
    expect(fetch).toHaveBeenCalledTimes(3);
  });

  it("reports a permission revoked after the attachment was rendered", async () => {
    installState.user = { id: "admin", system_role: "admin" };
    rs.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ detail: "Admin required" }), {
        status: 403,
      }),
    );
    const log = rs.spyOn(console, "error").mockImplementation(() => undefined);
    renderArchive();
    fireEvent.click(
      screen.getByRole("button", { name: `Install ${archive.filename}` }),
    );
    await waitFor(() =>
      expect(installState.error).toHaveBeenCalledWith(
        enUS.settings.skills.installAdminRequired,
      ),
    );
    expect(installState.success).not.toHaveBeenCalled();
    expect(log).toHaveBeenCalledTimes(1);
  });
});
