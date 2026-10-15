import { afterEach, beforeEach, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { StrictMode } from "react";

rs.mock("@/core/channels/api", () => ({
  connectChannelProvider: rs.fn(),
  listChannelProviders: rs.fn(),
  listChannelConnections: rs.fn(),
}));

import {
  WechatQRCompletion,
  type PendingWechatBinding,
} from "@/components/workspace/channels/wechat-qr-completion";
import {
  connectChannelProvider,
  listChannelProviders,
  listChannelConnections,
} from "@/core/channels/api";
import type { ChannelProvider, ChannelConnection } from "@/core/channels/types";
import { I18nProvider } from "@/core/i18n/context";

beforeEach(() => {
  rs.mocked(listChannelProviders).mockResolvedValue({
    enabled: true,
    providers: [],
  });
  rs.mocked(listChannelConnections).mockResolvedValue([]);
  rs.mocked(connectChannelProvider).mockResolvedValue({
    provider: "wechat",
    mode: "binding_code",
    code: "demo",
    instruction: "Send /connect demo",
    expires_in: 600,
  });
});
afterEach(() => {
  cleanup();
  rs.useRealTimers();
  rs.resetAllMocks();
});
function mount(connected = false, bindingToResume?: PendingWechatBinding) {
  const onDone = rs.fn();
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const view = (connected: boolean) => (
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        <I18nProvider initialLocale="en-US">
          <WechatQRCompletion
            provider={
              {
                provider: "wechat",
                connection_status: connected ? "connected" : "not_connected",
              } as ChannelProvider
            }
            onDone={onDone}
            onRestart={rs.fn()}
            bindingToResume={bindingToResume}
          />
        </I18nProvider>
      </QueryClientProvider>
    </StrictMode>
  );
  const { rerender } = render(view(connected));
  return {
    onDone,
    updateConnection: (connected: boolean) => rerender(view(connected)),
  };
}

it("keeps saved credentials and the binding instruction visible until connected", async () => {
  const { onDone } = mount();
  expect(await screen.findByText("/connect demo")).toBeTruthy();
  expect(screen.getByText("Token saved securely")).toBeTruthy();
  expect(onDone).not.toHaveBeenCalled();
  expect(connectChannelProvider).toHaveBeenCalledTimes(1);
  rs.mocked(listChannelConnections).mockResolvedValue([
    { provider: "wechat", status: "connected" } as ChannelConnection,
  ]);
  await screen.findByText("WeChat is connected", {}, { timeout: 4000 });
  fireEvent.click(screen.getByRole("button", { name: "Done" }));
  expect(onDone).toHaveBeenCalledTimes(1);
});

it("shows a stable success step when no user binding is required", async () => {
  const { onDone } = mount(true);
  expect(screen.getByText("WeChat is connected")).toBeTruthy();
  expect(connectChannelProvider).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Done" }));
  expect(onDone).toHaveBeenCalledTimes(1);
});

it("shows success when the provider connects before the binding poll finishes", async () => {
  rs.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "Date"] });
  let finishPoll!: (connections: ChannelConnection[]) => void;
  rs.mocked(listChannelConnections).mockReturnValueOnce(
    new Promise((resolve) => {
      finishPoll = resolve;
    }),
  );
  const { onDone, updateConnection } = mount();
  await act(() => rs.advanceTimersByTimeAsync(1));
  expect(screen.getByText("/connect demo")).toBeTruthy();
  await act(() => rs.advanceTimersByTimeAsync(2000));
  expect(listChannelConnections).toHaveBeenCalledTimes(1);

  updateConnection(true);
  expect(screen.getByText("WeChat is connected")).toBeTruthy();
  expect(screen.queryByText("/connect demo")).toBeNull();
  expect(screen.queryByRole("button", { name: "Scan again" })).toBeNull();
  expect(screen.getByRole("button", { name: "Done" })).toBeTruthy();

  await act(async () => finishPoll([]));
  await act(() => rs.advanceTimersByTimeAsync(600_000));
  expect(screen.getByText("WeChat is connected")).toBeTruthy();
  expect(listChannelConnections).toHaveBeenCalledTimes(1);
  expect(connectChannelProvider).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole("button", { name: "Done" }));
  expect(onDone).toHaveBeenCalledTimes(1);
});

it("keeps success when the provider connects while a binding request is pending", async () => {
  rs.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "Date"] });
  let failBinding!: (reason: Error) => void;
  rs.mocked(connectChannelProvider).mockReturnValueOnce(
    new Promise((_resolve, reject) => {
      failBinding = reject;
    }),
  );
  const { updateConnection } = mount();
  await act(() => rs.advanceTimersByTimeAsync(1));
  expect(connectChannelProvider).toHaveBeenCalledTimes(1);

  updateConnection(true);
  expect(screen.getByText("WeChat is connected")).toBeTruthy();
  await act(async () => failBinding(new Error("late binding failure")));
  await act(() => rs.advanceTimersByTimeAsync(600_000));
  expect(screen.getByText("WeChat is connected")).toBeTruthy();
  expect(screen.getByRole("button", { name: "Done" })).toBeTruthy();
  expect(listChannelConnections).not.toHaveBeenCalled();
});

it("retries account binding without asking the user to scan again", async () => {
  rs.mocked(connectChannelProvider).mockRejectedValueOnce(
    new Error("unavailable"),
  );
  mount();
  await screen.findByText(
    "Your token is saved, but account binding could not start. Try again.",
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Generate binding code" }),
  );
  expect(await screen.findByText("/connect demo")).toBeTruthy();
  await waitFor(() => expect(connectChannelProvider).toHaveBeenCalledTimes(2));
});

it("offers a new binding code when the old one expires", async () => {
  rs.mocked(connectChannelProvider).mockResolvedValueOnce({
    provider: "wechat",
    mode: "binding_code",
    code: "demo",
    instruction: "Send /connect demo",
    expires_in: 0.05,
  });
  mount();
  await screen.findByText(
    "This binding code has expired. Generate a new one; no need to scan again.",
  );
  expect(screen.queryByText("/connect demo")).toBeNull();
  expect(
    screen.getByRole("button", { name: "Generate binding code" }),
  ).toBeTruthy();
});

it("keeps the original command deadline across rescans and replaces it only after expiry", async () => {
  rs.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "Date"] });
  mount(false, { code: "already-on-phone", expiresAt: Date.now() + 5000 });
  await act(() => rs.advanceTimersByTimeAsync(1));
  expect(screen.getByText("/connect already-on-phone")).toBeTruthy();
  expect(connectChannelProvider).not.toHaveBeenCalled();
  await act(() => rs.advanceTimersByTimeAsync(5000));
  expect(screen.queryByText("/connect already-on-phone")).toBeNull();
  expect(screen.getByRole("button", { name: "Scan again" })).toBeTruthy();
  fireEvent.click(
    screen.getByRole("button", { name: "Generate binding code" }),
  );
  await act(() => rs.advanceTimersByTimeAsync(1));
  expect(screen.getByText("/connect demo")).toBeTruthy();
  expect(connectChannelProvider).toHaveBeenCalledTimes(1);
});
