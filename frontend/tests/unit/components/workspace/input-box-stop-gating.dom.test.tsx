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

rs.mock("next/navigation", () => ({
  useRouter: () => ({ push: rs.fn(), replace: rs.fn(), refresh: rs.fn() }),
  usePathname: () => "/workspace",
  useSearchParams: () => new URLSearchParams(),
}));

// The composer's model selector is irrelevant to stop gating; keep the
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

function renderComposer({
  canStopStreaming,
  onStop,
}: {
  canStopStreaming?: boolean;
  onStop: () => void;
}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const tree = (onStopProp: () => void): ReactNode => (
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
                status="streaming"
                context={{ mode: "flash" } as never}
                onStop={onStopProp}
                canStopStreaming={canStopStreaming}
              />
            </PromptInputProvider>
          </ThreadContext.Provider>
        </AuthProvider>
      </QueryClientProvider>
    </I18nProvider>
  );
  return render(tree(onStop));
}

afterEach(() => {
  rs.restoreAllMocks();
  cleanup();
});

describe("InputBox stop gating (runs:cancel)", () => {
  it("disables the stop affordance for a denied role and never fires onStop", () => {
    const onStop = rs.fn();
    const { container } = renderComposer({ canStopStreaming: false, onStop });

    const submit = getSubmitButton(container);
    expect(submit.disabled).toBe(true);

    fireEvent.click(submit);
    expect(onStop).not.toHaveBeenCalled();
  });

  it("explains the permission boundary on the disabled affordance", () => {
    const { container } = renderComposer({
      canStopStreaming: false,
      onStop: rs.fn(),
    });

    const submit = getSubmitButton(container);
    expect(submit.getAttribute("aria-label")).toContain("not permitted");
    expect(submit.title).toContain("not permitted");
  });

  it("keeps stop enabled for an unresolved permission list (default)", () => {
    const onStop = rs.fn();
    const { container } = renderComposer({ onStop });

    const submit = getSubmitButton(container);
    expect(submit.disabled).toBe(false);

    fireEvent.click(submit);
    expect(onStop).toHaveBeenCalledTimes(1);
  });

  it("keeps the base Submit accessible name when stop is not denied", () => {
    // Regression: passing an explicitly-undefined aria-label clobbered
    // PromptInputSubmit's default aria-label="Submit" via JSX spread,
    // stripping the submit control's accessible name in every
    // non-denied state (e2e locates the button by that name). Query by
    // role + name so the assertion resolves the accessible name the
    // same way e2e and assistive tech do, not via the raw attribute.
    renderComposer({ onStop: rs.fn() });

    // getByRole throws when no button exposes the "Submit" accessible
    // name, which is exactly the regression being guarded.
    const submit = screen.getByRole("button", { name: "Submit" });
    expect(submit.tagName).toBe("BUTTON");
  });
});
