import { afterEach, expect, rs, test } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";

const mocks = rs.hoisted(() => ({ usage: rs.fn() }));
rs.mock("@/core/usage/api", () => ({ fetchUsage: mocks.usage }));

import { useUsage } from "@/core/usage/hooks";

const clients: QueryClient[] = [];

afterEach(() => {
  cleanup();
  clients.splice(0).forEach((client) => client.clear());
  mocks.usage.mockReset();
});

test("account changes cancel obsolete reports and never reuse another owner's totals", async () => {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  clients.push(client);
  let finishAlice!: (value: { total_tokens: number }) => void;
  const alice = new Promise<{ total_tokens: number }>((resolve) => {
    finishAlice = resolve;
  });
  mocks.usage
    .mockReturnValueOnce(alice)
    .mockResolvedValue({ total_tokens: 200 });
  const { result, rerender } = renderHook(
    ({ owner }: { owner: string | undefined }) => useUsage(owner, 7, 480, true),
    {
      initialProps: { owner: "alice" as string | undefined },
      wrapper: ({ children }: { children: ReactNode }) => (
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
      ),
    },
  );
  await waitFor(() => expect(mocks.usage).toHaveBeenCalledTimes(1));
  const aliceSignal = mocks.usage.mock.calls[0]![2] as AbortSignal;
  rerender({ owner: undefined });
  expect(aliceSignal.aborted).toBe(true);
  expect(result.current.data).toBeUndefined();
  expect(mocks.usage).toHaveBeenCalledTimes(1);
  rerender({ owner: "bob" });
  await waitFor(() => expect(result.current.data?.total_tokens).toBe(200));
  await act(async () => {
    finishAlice({ total_tokens: 999 });
    await alice;
  });
  expect(result.current.data?.total_tokens).toBe(200);
});
