import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";

import { PromptInputProvider } from "@/components/ai-elements/prompt-input";
import { InputBox } from "@/components/workspace/input-box";
import { ThreadContext } from "@/components/workspace/messages/context";
import { AuthProvider } from "@/core/auth/AuthProvider";
import { I18nProvider } from "@/core/i18n/context";
import type { ContextUsageBreakdown } from "@/core/threads/token-usage";

rs.mock("next/navigation", () => ({
  useRouter: () => ({ push: rs.fn(), replace: rs.fn(), refresh: rs.fn() }),
  usePathname: () => "/workspace",
  useSearchParams: () => new URLSearchParams(),
}));

rs.mock("@/core/models/hooks", () => ({
  useModels: () => ({
    models: [
      {
        name: "model-1",
        model: "model-1",
        display_name: "Model 1",
        context_window: 4000,
      },
    ],
    tokenUsageEnabled: true,
    isLoading: false,
    isFetching: false,
    error: null,
    refetch: rs.fn(),
  }),
}));

const BREAKDOWN: ContextUsageBreakdown = {
  totalTokens: 1000,
  percentage: 25,
  remainingTokens: 3000,
  systemPromptTokens: 100,
  builtinToolsTokens: 200,
  mcpToolsTokens: 50,
  skillBodyTokens: 25,
  memoryTokens: 30,
  taskStateTokens: 40,
  otherInjectionTokens: 5,
  conversationTokens: 500,
  toolResultTokens: 50,
  modelName: "model-1",
  contextWindow: 4000,
  capturedAt: "2026-11-13T00:00:00Z",
};

afterEach(() => {
  cleanup();
});

function renderComposer({
  contextUsageEnabled,
  contextUsageBreakdown = null,
  onContextUsageOpen,
}: {
  contextUsageEnabled: boolean;
  contextUsageBreakdown?: ContextUsageBreakdown | null;
  onContextUsageOpen?: () => void;
}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const tree: ReactNode = (
    <I18nProvider initialLocale="en-US">
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
                onSubmit={rs.fn()}
                contextUsageEnabled={contextUsageEnabled}
                contextUsageBreakdown={contextUsageBreakdown}
                onContextUsageOpen={onContextUsageOpen}
              />
            </PromptInputProvider>
          </ThreadContext.Provider>
        </AuthProvider>
      </QueryClientProvider>
    </I18nProvider>
  );
  return render(tree);
}

describe("InputBox context usage ring", () => {
  it("hides the ring when context usage is disabled", () => {
    renderComposer({ contextUsageEnabled: false });

    expect(screen.queryByTestId("context-usage-ring")).toBeNull();
  });

  it("renders the ring and forwards opening the popover", () => {
    const onContextUsageOpen = rs.fn();
    renderComposer({
      contextUsageEnabled: true,
      contextUsageBreakdown: BREAKDOWN,
      onContextUsageOpen,
    });

    fireEvent.click(screen.getByTestId("context-usage-ring"));

    expect(onContextUsageOpen).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId("context-usage-popover")).toBeTruthy();
  });
});
