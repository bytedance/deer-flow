import { afterEach, describe, expect, it, rs } from "@rstest/core";
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

// The composer's model selector is irrelevant to send gating; keep the
// react-query + network machinery out of the way entirely.
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

function getSubmitButton(container: HTMLElement): HTMLButtonElement {
  const button = container.querySelector('button[type="submit"]');
  if (!(button instanceof HTMLButtonElement)) {
    throw new Error("submit button not rendered");
  }
  return button;
}

function typeText(container: HTMLElement, value: string): void {
  const textarea = container.querySelector("textarea");
  if (!(textarea instanceof HTMLTextAreaElement)) {
    throw new Error("composer textarea not rendered");
  }
  fireEvent.change(textarea, { target: { value } });
}

function renderComposer({
  canCreateRuns,
  onSubmit,
}: {
  canCreateRuns?: boolean;
  onSubmit: () => void;
}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const tree = (onSubmitProp: () => void): ReactNode => (
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
                threadId="thread-1"
                status="ready"
                context={{ mode: "flash" } as never}
                onSubmit={onSubmitProp}
                canCreateRuns={canCreateRuns}
              />
            </PromptInputProvider>
          </ThreadContext.Provider>
        </AuthProvider>
      </QueryClientProvider>
    </I18nProvider>
  );
  return render(tree(onSubmit));
}

afterEach(() => {
  rs.restoreAllMocks();
  cleanup();
});

describe("InputBox send gating (runs:create)", () => {
  it("disables the send affordance for a denied role and never fires onSubmit", () => {
    const onSubmit = rs.fn();
    const { container } = renderComposer({
      canCreateRuns: false,
      onSubmit,
    });

    const submit = getSubmitButton(container);
    expect(submit.disabled).toBe(true);

    fireEvent.click(submit);
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("blocks the Enter submit path for a denied role (handler-level gate)", async () => {
    const onSubmit = rs.fn();
    const { container } = renderComposer({
      canCreateRuns: false,
      onSubmit,
    });

    typeText(container, "hello");
    const form = container.querySelector("form");
    if (!(form instanceof HTMLFormElement)) {
      throw new Error("composer form not rendered");
    }
    fireEvent.submit(form);
    // PromptInput resolves the submit through a microtask chain (file
    // conversion promise) before calling onSubmit; flush it so an
    // ungated composer provably fires and this test is a real guard.
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("explains the permission boundary on the disabled affordance", () => {
    const { container } = renderComposer({
      canCreateRuns: false,
      onSubmit: rs.fn(),
    });

    const submit = getSubmitButton(container);
    expect(submit.getAttribute("aria-label")).toContain("not permitted");
    expect(submit.title).toContain("not permitted");
  });

  it("keeps send enabled for an unresolved permission list (default)", async () => {
    const onSubmit = rs.fn();
    const { container } = renderComposer({ onSubmit });

    const submit = getSubmitButton(container);
    expect(submit.disabled).toBe(false);

    typeText(container, "hello");
    const form = container.querySelector("form");
    if (!(form instanceof HTMLFormElement)) {
      throw new Error("composer form not rendered");
    }
    fireEvent.submit(form);
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
  });

  it("keeps the base Submit accessible name when send is not denied", () => {
    // Mirror of the stop-gating regression: the aria-label must be spread
    // conditionally, never explicitly-undefined, or it clobbers
    // PromptInputSubmit's default aria-label="Submit".
    renderComposer({ onSubmit: rs.fn() });

    const submit = screen.getByRole("button", { name: "Submit" });
    expect(submit.tagName).toBe("BUTTON");
  });
});
