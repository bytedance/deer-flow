import { afterEach, beforeEach, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, renderHook } from "@testing-library/react";
import { StrictMode, type ReactNode } from "react";

rs.mock("@/core/channels/api", () => ({
  connectChannelProvider: rs.fn(),
  listChannelProviders: rs.fn(),
  listChannelConnections: rs.fn(),
}));

import {
  connectChannelProvider,
  listChannelConnections,
  listChannelProviders,
} from "@/core/channels/api";
import type {
  ChannelConnectResponse,
  ChannelConnection,
  ChannelProvider,
} from "@/core/channels/types";
import { useBindingCode } from "@/core/channels/use-binding-code";

function minted(code: string, expiresIn = 600): ChannelConnectResponse {
  return {
    provider: "discord",
    mode: "binding_code",
    code,
    instruction: `Send /connect ${code}`,
    expires_in: expiresIn,
  };
}

beforeEach(() => {
  rs.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "Date"] });
  rs.mocked(listChannelProviders).mockResolvedValue({
    enabled: true,
    providers: [],
  });
  rs.mocked(listChannelConnections).mockResolvedValue([]);
  rs.mocked(connectChannelProvider).mockResolvedValue(minted("abc123"));
});
afterEach(() => {
  cleanup();
  rs.useRealTimers();
  rs.resetAllMocks();
});

function mount(provider = "discord") {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <StrictMode>
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    </StrictMode>
  );
  return renderHook(() => useBindingCode({ provider }), { wrapper });
}

it("binds the requested provider and ignores other apps' connections", async () => {
  const { result } = mount();
  await act(() => rs.advanceTimersByTimeAsync(1));
  expect(connectChannelProvider).toHaveBeenCalledExactlyOnceWith("discord");
  expect(result.current.stage).toBe("binding");
  expect(result.current.command).toBe("/connect abc123");

  rs.mocked(listChannelConnections).mockResolvedValue([
    { provider: "slack", status: "connected" } as ChannelConnection,
  ]);
  await act(() => rs.advanceTimersByTimeAsync(2000));
  expect(result.current.stage).toBe("binding");

  rs.mocked(listChannelConnections).mockResolvedValue([
    { provider: "discord", status: "connected" } as ChannelConnection,
  ]);
  await act(() => rs.advanceTimersByTimeAsync(2000));
  expect(result.current.stage).toBe("connected");
});

it("mints no code when the provider already reports a connection", async () => {
  rs.mocked(listChannelProviders).mockResolvedValue({
    enabled: true,
    providers: [
      {
        provider: "discord",
        connection_status: "connected",
      } as ChannelProvider,
    ],
  });
  const { result } = mount();
  await act(() => rs.advanceTimersByTimeAsync(1));
  expect(result.current.stage).toBe("connected");
  expect(connectChannelProvider).not.toHaveBeenCalled();
});

it("stops polling when the caller unmounts", async () => {
  const { unmount } = mount();
  await act(() => rs.advanceTimersByTimeAsync(2000));
  expect(listChannelConnections).toHaveBeenCalledTimes(1);
  unmount();
  await act(() => rs.advanceTimersByTimeAsync(10_000));
  expect(listChannelConnections).toHaveBeenCalledTimes(1);
});

it("starts every new code uncopied", async () => {
  rs.mocked(connectChannelProvider)
    .mockResolvedValueOnce(minted("first", 60))
    .mockResolvedValueOnce(minted("second"));
  const { result } = mount();
  await act(() => rs.advanceTimersByTimeAsync(1));
  act(() => result.current.reportCopy(true));
  expect(result.current.copied).toBe(true);

  await act(() => rs.advanceTimersByTimeAsync(60_000));
  expect(result.current.stage).toBe("expired");
  act(() => result.current.retry());
  await act(() => rs.advanceTimersByTimeAsync(1));
  expect(result.current.command).toBe("/connect second");
  expect(result.current.copied).toBe(false);
});
