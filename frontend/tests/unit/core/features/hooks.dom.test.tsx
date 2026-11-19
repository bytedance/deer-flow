import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";

import { fetchConversationReferencesCapability } from "@/core/features/api";
import { useConversationReferencesCapability } from "@/core/features/hooks";

rs.mock("@/core/features/api", () => ({
  fetchConversationReferencesCapability: rs.fn(),
}));
const fetchCapability = rs.mocked(fetchConversationReferencesCapability);
function renderCapability() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return renderHook(useConversationReferencesCapability, {
    wrapper: ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    ),
  });
}
afterEach(() => {
  cleanup();
  fetchCapability.mockReset();
});

describe("conversation reference discovery", () => {
  it("distinguishes an initial failure from a confirmed disable and supports retry", async () => {
    fetchCapability.mockRejectedValueOnce(new Error("503 temporary"));
    const { result } = renderCapability();
    expect(result.current.isLoading).toBe(true);
    expect(result.current.isSuccess).toBe(false);
    await waitFor(() => expect(result.current.error).toBeTruthy());
    expect(result.current.isLoading).toBe(false);
    expect(result.current.isSuccess).toBe(false);
    fetchCapability.mockResolvedValueOnce({ enabled: true, maxReferences: 4 });
    await result.current.refetch();
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current).toMatchObject({
      enabled: true,
      maxReferences: 4,
      error: null,
    });
  });
  it("marks a successful disabled response as authoritative", async () => {
    fetchCapability.mockResolvedValueOnce({ enabled: false, maxReferences: 0 });
    const { result } = renderCapability();
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current).toMatchObject({
      enabled: false,
      isLoading: false,
      error: null,
    });
  });
  it("does not expose a cached enabled capability after a failed refresh", async () => {
    fetchCapability.mockResolvedValueOnce({ enabled: true, maxReferences: 3 });
    const { result } = renderCapability();
    await waitFor(() => expect(result.current.enabled).toBe(true));
    fetchCapability.mockRejectedValueOnce(new Error("network unavailable"));
    await result.current.refetch();
    await waitFor(() => expect(result.current.error).toBeTruthy());
    expect(result.current).toMatchObject({
      enabled: false,
      isSuccess: false,
      isLoading: false,
    });
  });
});
