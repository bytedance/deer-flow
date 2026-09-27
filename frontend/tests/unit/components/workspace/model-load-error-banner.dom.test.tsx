import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
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

rs.mock("@/core/auth/AuthProvider", () => ({
  useAuth: rs.fn(),
}));

import { ModelLoadErrorBanner } from "@/components/workspace/model-load-error-banner";
import { UnauthorizedError } from "@/core/api/errors";
import { useAuth } from "@/core/auth/AuthProvider";
import type { User } from "@/core/auth/types";
import { loadModels } from "@/core/models/api";
import { MODELS_QUERY_KEY, useModels } from "@/core/models/hooks";
import type { ModelsResponse } from "@/core/models/types";

const mockedLoadModels = rs.mocked(loadModels);
const mockedUseAuth = rs.mocked(useAuth);
const fakeUser = {} as User;

function createAuthState(user: User | null): ReturnType<typeof useAuth> {
  return {
    user,
    isAuthenticated: user !== null,
    isLoading: false,
    logout: rs.fn(),
    refreshUser: rs.fn(),
    applyUser: rs.fn(),
  };
}

function createDeferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((next) => {
    resolve = next;
  });
  return { promise, resolve };
}

beforeEach(() => {
  mockedUseAuth.mockReturnValue(createAuthState(fakeUser));
});

afterEach(() => {
  cleanup();
  mockedLoadModels.mockReset();
  mockedUseAuth.mockReset();
});

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, retryDelay: 0 },
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

  it("limits automatic model loading retries before surfacing the error", async () => {
    mockedLoadModels.mockRejectedValue(new Error("Gateway returned 503"));
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retryDelay: 0 },
      },
    });

    function RetryPolicyWrapper({ children }: PropsWithChildren) {
      return (
        <QueryClientProvider client={queryClient}>
          {children}
        </QueryClientProvider>
      );
    }

    render(
      <>
        <ModelLoadErrorBanner />
        <ModelConsumer />
      </>,
      { wrapper: RetryPolicyWrapper },
    );

    expect(await screen.findByRole("alert")).not.toBeNull();
    expect(mockedLoadModels).toHaveBeenCalledTimes(2);
  });

  it("shows one actionable error for all model consumers and clears after retry", async () => {
    const retryResult = createDeferred<ModelsResponse>();
    mockedLoadModels
      .mockRejectedValueOnce(new Error("Gateway returned 503"))
      .mockRejectedValueOnce(new Error("Gateway returned 503"))
      .mockImplementationOnce(() => retryResult.promise);
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
    expect(mockedLoadModels).toHaveBeenCalledTimes(2);

    fireEvent.click(screen.getByRole("button", { name: "Retry" }));

    const retryingButton = await screen.findByRole("button", {
      name: "Retrying…",
    });
    expect((retryingButton as HTMLButtonElement).disabled).toBe(true);

    retryResult.resolve({
      models: [],
      token_usage: { enabled: false },
    });

    await waitFor(() => {
      expect(screen.queryByRole("alert")).toBeNull();
    });
    expect(mockedLoadModels).toHaveBeenCalledTimes(3);
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
    expect(mockedLoadModels).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("suppresses a model symptom only while the gateway banner is visible", async () => {
    mockedUseAuth.mockReturnValue(createAuthState(null));
    mockedLoadModels.mockRejectedValue(new Error("Gateway returned 503"));
    const { queryClient, QueryWrapper } = createWrapper();

    const renderView = () => (
      <>
        <ModelLoadErrorBanner gatewayUnavailable />
        <ModelConsumer />
      </>
    );
    const { rerender } = render(renderView(), { wrapper: QueryWrapper });

    await waitFor(() => {
      expect(queryClient.getQueryState(MODELS_QUERY_KEY)?.status).toBe("error");
    });
    expect(screen.queryByRole("alert")).toBeNull();

    mockedUseAuth.mockReturnValue(createAuthState(fakeUser));
    rerender(renderView());

    expect(await screen.findByRole("alert")).not.toBeNull();
  });

  it("keeps the error visible without showing manual retry progress during a shared refetch", async () => {
    const backgroundResult = createDeferred<ModelsResponse>();
    mockedLoadModels
      .mockRejectedValueOnce(new Error("Gateway returned 503"))
      .mockRejectedValueOnce(new Error("Gateway returned 503"))
      .mockImplementationOnce(() => backgroundResult.promise);
    const { queryClient, QueryWrapper } = createWrapper();

    render(
      <>
        <ModelLoadErrorBanner />
        <ModelConsumer />
      </>,
      { wrapper: QueryWrapper },
    );

    await screen.findByRole("alert");
    const backgroundRefetch = queryClient.refetchQueries({
      queryKey: MODELS_QUERY_KEY,
    });
    await waitFor(() => {
      expect(mockedLoadModels).toHaveBeenCalledTimes(3);
    });

    expect(screen.getByRole("alert")).not.toBeNull();
    expect(screen.queryByRole("button", { name: "Retrying…" })).toBeNull();

    backgroundResult.resolve({
      models: [],
      token_usage: { enabled: false },
    });
    await backgroundRefetch;
  });
});
