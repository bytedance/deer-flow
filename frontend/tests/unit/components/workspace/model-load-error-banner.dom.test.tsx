import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import type { PropsWithChildren } from "react";

rs.mock("@/core/models/api", () => ({
  loadModels: rs.fn(),
}));

rs.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({
    locale: "en-US",
    t: {
      workspace: {
        modelLoadFailed:
          "Models couldn't be loaded. Model selection and token usage may be unavailable.",
        modelLoadRetry: "Retry",
        modelLoadRetrying: "Retrying…",
      },
    },
    changeLocale: rs.fn(),
  }),
}));

import { ModelLoadErrorBanner } from "@/components/workspace/model-load-error-banner";
import { UnauthorizedError } from "@/core/api/errors";
import { loadModels } from "@/core/models/api";
import { MODELS_QUERY_KEY, useModels } from "@/core/models/hooks";

const mockedLoadModels = rs.mocked(loadModels);

afterEach(() => {
  cleanup();
  mockedLoadModels.mockReset();
});

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });

  function QueryWrapper({ children }: PropsWithChildren) {
    return (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
  }

  return { queryClient, QueryWrapper };
}

function ModelConsumer() {
  useModels();
  return null;
}

describe("ModelLoadErrorBanner", () => {
  it("observes model failures without starting an extra request", async () => {
    const { QueryWrapper } = createWrapper();
    render(<ModelLoadErrorBanner />, { wrapper: QueryWrapper });

    await Promise.resolve();

    expect(mockedLoadModels).not.toHaveBeenCalled();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("shows one actionable error for all model consumers and clears after retry", async () => {
    mockedLoadModels
      .mockRejectedValueOnce(new Error("Gateway returned 503"))
      .mockResolvedValueOnce({
        models: [],
        token_usage: { enabled: false },
      });
    const { QueryWrapper } = createWrapper();

    render(
      <>
        <ModelLoadErrorBanner />
        <ModelConsumer />
        <ModelConsumer />
      </>,
      { wrapper: QueryWrapper },
    );

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Models couldn't be loaded");
    expect(alert.textContent).not.toContain("Gateway returned 503");
    expect(screen.getAllByRole("alert")).toHaveLength(1);
    expect(mockedLoadModels).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "Retry" }));

    await waitFor(() => {
      expect(screen.queryByRole("alert")).toBeNull();
    });
    expect(mockedLoadModels).toHaveBeenCalledTimes(2);
  });

  it("does not duplicate the login redirect with a model warning", async () => {
    mockedLoadModels.mockRejectedValueOnce(new UnauthorizedError());
    const { queryClient, QueryWrapper } = createWrapper();

    render(
      <>
        <ModelLoadErrorBanner />
        <ModelConsumer />
      </>,
      { wrapper: QueryWrapper },
    );

    await waitFor(() => {
      expect(queryClient.getQueryState(MODELS_QUERY_KEY)?.status).toBe("error");
    });
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
