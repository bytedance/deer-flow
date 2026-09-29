import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";

import { PromptInputProvider } from "@/components/ai-elements/prompt-input";
import { InputBox } from "@/components/workspace/input-box";
import { ThreadContext } from "@/components/workspace/messages/context";
import { AuthProvider } from "@/core/auth/AuthProvider";
import { DEFAULT_LOCALE } from "@/core/i18n";
import { I18nProvider } from "@/core/i18n/context";
import { COMPOSITION_CONFIRM_ENTER_MS } from "@/lib/ime";

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
function renderComposer(threadId: string) {
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

/** Focus the composer and type a leading slash query that opens the catalog. */
function openSkillCatalog(container: HTMLElement): HTMLTextAreaElement {
  const textarea = container.querySelector("textarea");
  if (!(textarea instanceof HTMLTextAreaElement)) {
    throw new Error("composer textarea not rendered");
  }
  fireEvent.focus(textarea);
  fireEvent.change(textarea, { target: { value: "/res" } });
  screen.getByRole("listbox", { name: "Skill suggestions" });
  return textarea;
}

afterEach(() => {
  rs.restoreAllMocks();
  window.sessionStorage.clear();
  cleanup();
});

describe("InputBox skill suggestion IME handling", () => {
  it("leaves Enter to the IME candidate window while the catalog is open", () => {
    const { container } = renderComposer("thread-ime-composing");
    const textarea = openSkillCatalog(container);

    // 229 is the keyCode browsers report for a keydown consumed by an active
    // IME composition; the catalog must not claim it.
    fireEvent.keyDown(textarea, { key: "Enter", keyCode: 229 });

    expect(
      screen.queryByRole("button", { name: "Remove /research" }),
    ).toBeNull();
    expect(textarea.value).toBe("/res");
  });

  it("does not apply a suggestion for the Enter that follows compositionend", () => {
    const { container } = renderComposer("thread-ime-composition-end");
    const textarea = openSkillCatalog(container);

    // Safari reports the confirming Enter after compositionend, with neither
    // isComposing nor keyCode 229 set.
    fireEvent.compositionEnd(textarea);
    fireEvent.keyDown(textarea, { key: "Enter", keyCode: 13 });

    expect(
      screen.queryByRole("button", { name: "Remove /research" }),
    ).toBeNull();
    expect(textarea.value).toBe("/res");
  });

  it("still selects the highlighted skill once the confirm window has passed", () => {
    const { container } = renderComposer("thread-ime-after-window");
    const textarea = openSkillCatalog(container);
    const endedAt = Date.now();
    const now = rs.spyOn(Date, "now");
    now.mockReturnValue(endedAt);
    fireEvent.compositionEnd(textarea);
    now.mockReturnValue(endedAt + COMPOSITION_CONFIRM_ENTER_MS);

    fireEvent.keyDown(textarea, { key: "Enter", keyCode: 13 });

    expect(
      screen.getByRole("button", { name: "Remove /research" }),
    ).toBeTruthy();
  });

  it("still selects the highlighted skill on a plain Enter", () => {
    const { container } = renderComposer("thread-plain-enter");
    const textarea = openSkillCatalog(container);

    fireEvent.keyDown(textarea, { key: "Enter" });

    expect(
      screen.getByRole("button", { name: "Remove /research" }),
    ).toBeTruthy();
  });
});
