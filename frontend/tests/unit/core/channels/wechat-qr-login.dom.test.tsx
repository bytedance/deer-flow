import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
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
  startWechatQRLogin: rs.fn(),
  pollWechatQRLogin: rs.fn(),
  cancelWechatQRLogin: rs.fn(),
  connectChannelProvider: rs.fn(),
  listChannelConnections: rs.fn(),
  listChannelProviders: rs.fn(),
}));

import { ChannelRuntimeConfigDialog } from "@/components/workspace/channels/channel-runtime-config-dialog";
import { WechatQRLogin } from "@/components/workspace/channels/wechat-qr-login";
import {
  cancelWechatQRLogin,
  connectChannelProvider,
  listChannelConnections,
  listChannelProviders,
  pollWechatQRLogin,
  startWechatQRLogin,
} from "@/core/channels/api";
import type {
  ChannelProvider,
  WechatQRLoginSession,
} from "@/core/channels/types";
import { I18nProvider } from "@/core/i18n/context";

const session: WechatQRLoginSession = {
  id: "session-1",
  status: "pending",
  qrcode_content: "https://example.com/scan",
  expires_in: 180,
  provider: null,
};
const provider = { provider: "wechat", configured: true } as ChannelProvider;
function mount(onConfigured = rs.fn()) {
  return {
    onConfigured,
    ...render(
      <QueryClientProvider client={new QueryClient()}>
        <I18nProvider initialLocale="en-US">
          <WechatQRLogin onConfigured={onConfigured} />
        </I18nProvider>
      </QueryClientProvider>,
    ),
  };
}

beforeEach(() => {
  rs.mocked(startWechatQRLogin).mockResolvedValue(session);
  rs.mocked(pollWechatQRLogin).mockResolvedValue({
    ...session,
    status: "expired",
  });
  rs.mocked(cancelWechatQRLogin).mockResolvedValue(undefined);
});
afterEach(() => {
  cleanup();
  rs.useRealTimers();
  rs.resetAllMocks();
});

describe("WeChat QR login", () => {
  it("renders a local QR code and offers retry after expiry", async () => {
    mount();
    expect(await screen.findByTitle("WeChat login QR code")).toBeTruthy();
    expect(
      await screen.findByText(
        "This QR code has expired. Generate a new one.",
        {},
        { timeout: 4000 },
      ),
    ).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Refresh QR code" }));
    await waitFor(() => expect(startWechatQRLogin).toHaveBeenCalledTimes(2));
    expect(cancelWechatQRLogin).toHaveBeenCalledWith("session-1");
  });

  it("continues with the configured provider once confirmation succeeds", async () => {
    rs.mocked(pollWechatQRLogin).mockResolvedValue({
      ...session,
      status: "confirmed",
      provider,
    });
    const { onConfigured } = mount();
    await waitFor(() => expect(onConfigured).toHaveBeenCalledWith(provider), {
      timeout: 4000,
    });
    expect(onConfigured).toHaveBeenCalledTimes(1);
  });

  it("cancels a start response arriving after the dialog closes", async () => {
    let resolve!: (session: WechatQRLoginSession) => void;
    rs.mocked(startWechatQRLogin).mockReturnValue(
      new Promise((done) => {
        resolve = done;
      }),
    );
    const { unmount, onConfigured } = mount();
    await waitFor(() => expect(startWechatQRLogin).toHaveBeenCalled());
    unmount();
    await act(async () => {
      resolve(session);
    });
    expect(cancelWechatQRLogin).toHaveBeenCalledWith("session-1");
    expect(pollWechatQRLogin).not.toHaveBeenCalled();
    expect(onConfigured).not.toHaveBeenCalled();
  });
});

function mountDialog(
  configured = false,
  initialStep: "setup" | "binding" = "setup",
) {
  const onSubmit = rs.fn();
  render(
    <QueryClientProvider client={new QueryClient()}>
      <I18nProvider initialLocale="en-US">
        <ChannelRuntimeConfigDialog
          provider={{
            ...provider,
            display_name: "WeChat",
            configured,
            credential_fields: [
              {
                name: "bot_token",
                label: "Bot token",
                type: "password",
                required: true,
              },
            ],
            credential_values: configured ? { bot_token: "********" } : {},
          }}
          open
          initialStep={initialStep}
          submitting={false}
          onOpenChange={rs.fn()}
          onConfigured={rs.fn()}
          onSubmit={onSubmit}
        />
      </I18nProvider>
    </QueryClientProvider>,
  );
  return { onSubmit };
}

it("keeps the token draft while switching methods and cancels the QR session", async () => {
  mountDialog();
  expect(
    screen
      .getByRole("tab", { name: "Scan QR code" })
      .getAttribute("aria-selected"),
  ).toBe("true");
  await screen.findByTitle("WeChat login QR code");
  fireEvent.mouseDown(screen.getByRole("tab", { name: "Use token" }), {
    button: 0,
    ctrlKey: false,
  });
  const input = screen.getByLabelText("Bot token");
  fireEvent.change(input, { target: { value: "draft-token" } });
  await waitFor(() =>
    expect(cancelWechatQRLogin).toHaveBeenCalledWith("session-1"),
  );
  fireEvent.mouseDown(screen.getByRole("tab", { name: "Scan QR code" }), {
    button: 0,
    ctrlKey: false,
  });
  await waitFor(() => expect(startWechatQRLogin).toHaveBeenCalledTimes(2));
  fireEvent.mouseDown(screen.getByRole("tab", { name: "Use token" }), {
    button: 0,
    ctrlKey: false,
  });
  expect(screen.getByLabelText<HTMLInputElement>("Bot token").value).toBe(
    "draft-token",
  );
});

it("opens existing credentials in the token tab without starting QR login", () => {
  const { onSubmit } = mountDialog(true);
  expect(
    screen
      .getByRole("tab", { name: "Use token" })
      .getAttribute("aria-selected"),
  ).toBe("true");
  expect(screen.getByLabelText<HTMLInputElement>("Bot token").value).toBe(
    "********",
  );
  expect(startWechatQRLogin).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
  expect(onSubmit).toHaveBeenCalledWith(
    expect.objectContaining({ provider: "wechat" }),
    { bot_token: "********" },
  );
});

it("does not create competing sessions during Strict Mode's effect replay", async () => {
  render(
    <StrictMode>
      <QueryClientProvider client={new QueryClient()}>
        <I18nProvider initialLocale="en-US">
          <WechatQRLogin onConfigured={rs.fn()} />
        </I18nProvider>
      </QueryClientProvider>
    </StrictMode>,
  );
  await screen.findByTitle("WeChat login QR code");
  expect(startWechatQRLogin).toHaveBeenCalledTimes(1);
  expect(cancelWechatQRLogin).not.toHaveBeenCalled();
});

it("asks for the phone pairing code and shows a rejected code inline", async () => {
  rs.mocked(pollWechatQRLogin)
    .mockResolvedValueOnce({ ...session, status: "verification_required" })
    .mockResolvedValueOnce({
      ...session,
      status: "verification_required",
      error: "verification_rejected",
    })
    .mockResolvedValueOnce({ ...session, status: "confirmed", provider });
  const { onConfigured } = mount();
  const input = await screen.findByLabelText(
    "Pairing code",
    {},
    { timeout: 4000 },
  );
  fireEvent.change(input, { target: { value: "123456" } });
  fireEvent.click(screen.getByRole("button", { name: "Continue connecting" }));
  expect(
    await screen.findByText(
      "The code did not match. Check the digits on your phone and try again.",
    ),
  ).toBeTruthy();
  expect(pollWechatQRLogin).toHaveBeenLastCalledWith(
    "session-1",
    expect.any(AbortSignal),
    "123456",
  );
  fireEvent.change(input, { target: { value: "654321" } });
  fireEvent.keyDown(input, { key: "Enter" });
  await waitFor(() => expect(onConfigured).toHaveBeenCalledTimes(1));
});

it("keeps the same QR while automatically retrying temporary network errors", async () => {
  rs.mocked(pollWechatQRLogin)
    .mockResolvedValueOnce({ ...session, error: "network" })
    .mockResolvedValueOnce({ ...session, status: "confirmed", provider });
  const { onConfigured } = mount();
  await screen.findByText(
    "WeChat is temporarily unreachable. Retrying automatically…",
    {},
    { timeout: 4000 },
  );
  expect(screen.getByTitle("WeChat login QR code")).toBeTruthy();
  await waitFor(() => expect(onConfigured).toHaveBeenCalledTimes(1), {
    timeout: 4000,
  });
  expect(startWechatQRLogin).toHaveBeenCalledTimes(1);
});

it.each([
  { status: "confirmed", provider },
  { status: "verification_required", error: "verification_rejected" },
  { status: "expired" },
  { status: "failed", error: "verification_blocked" },
] satisfies Partial<WechatQRLoginSession>[])(
  "keeps polling a submitted pairing code until $status",
  async (outcome) => {
    rs.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "Date"] });
    rs.mocked(pollWechatQRLogin)
      .mockResolvedValueOnce({ ...session, status: "verification_required" })
      // Backend wait/redirect responses after submission normalize to scanned.
      .mockResolvedValueOnce({ ...session, status: "scanned" })
      .mockResolvedValueOnce({
        ...session,
        status: "scanned",
        error: "network",
      })
      .mockResolvedValueOnce({ ...session, status: "scanned" })
      .mockResolvedValueOnce({ ...session, ...outcome });
    const { onConfigured } = mount();
    await act(() => rs.advanceTimersByTimeAsync(1501));
    fireEvent.change(screen.getByLabelText("Pairing code"), {
      target: { value: "123456" },
    });
    await act(async () => {
      fireEvent.click(
        screen.getByRole("button", { name: "Continue connecting" }),
      );
    });
    expect(pollWechatQRLogin).toHaveBeenNthCalledWith(
      2,
      "session-1",
      expect.any(AbortSignal),
      "123456",
    );
    expect(screen.queryByLabelText("Pairing code")).toBeNull();
    expect(onConfigured).not.toHaveBeenCalled();

    for (let call = 3; call <= 5; call++) {
      await act(() => rs.advanceTimersByTimeAsync(1500));
      // The server retains the submitted code; the browser need not resend it.
      expect(pollWechatQRLogin).toHaveBeenNthCalledWith(
        call,
        "session-1",
        expect.any(AbortSignal),
        undefined,
      );
    }
    if (outcome.status === "confirmed") {
      expect(onConfigured).toHaveBeenCalledExactlyOnceWith(provider);
    } else {
      expect(onConfigured).not.toHaveBeenCalled();
      if (outcome.status === "verification_required") {
        expect(
          screen.getByLabelText<HTMLInputElement>("Pairing code").value,
        ).toBe("");
        expect(
          screen.getByText(
            "The code did not match. Check the digits on your phone and try again.",
          ),
        ).toBeTruthy();
      } else {
        expect(
          screen.getByRole("button", { name: "Refresh QR code" }),
        ).toBeTruthy();
      }
    }
    await act(() => rs.advanceTimersByTimeAsync(5000));
    expect(pollWechatQRLogin).toHaveBeenCalledTimes(5);
    expect(startWechatQRLogin).toHaveBeenCalledTimes(1);
  },
);

it("restarts scanning while keeping the unexpired phone command and ignoring an old poll", async () => {
  rs.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "Date"] });
  rs.mocked(listChannelProviders).mockResolvedValue({
    enabled: true,
    providers: [],
  });
  rs.mocked(connectChannelProvider).mockResolvedValue({
    provider: "wechat",
    mode: "binding_code",
    code: "copied-to-phone",
    instruction: "Send /connect copied-to-phone",
    expires_in: 600,
  });
  let resolveOldPoll!: (connections: []) => void;
  rs.mocked(listChannelConnections)
    .mockReturnValueOnce(
      new Promise((resolve) => {
        resolveOldPoll = resolve;
      }),
    )
    .mockResolvedValue([]);
  rs.mocked(startWechatQRLogin)
    .mockResolvedValueOnce(session)
    .mockResolvedValueOnce({
      ...session,
      id: "new-session",
      qrcode_content: "https://example.com/new-scan",
    });
  rs.mocked(pollWechatQRLogin)
    .mockResolvedValueOnce({ ...session, status: "confirmed", provider })
    .mockResolvedValue({ ...session, id: "new-session", status: "pending" });
  mountDialog();
  await act(() => rs.advanceTimersByTimeAsync(1));
  await act(() => rs.advanceTimersByTimeAsync(1500));
  await act(() => rs.advanceTimersByTimeAsync(1));
  expect(screen.getByText("/connect copied-to-phone")).toBeTruthy();
  await act(() => rs.advanceTimersByTimeAsync(2000));
  expect(listChannelConnections).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole("button", { name: "Scan again" }));
  await act(() => rs.advanceTimersByTimeAsync(1));
  expect(screen.getByTitle("WeChat login QR code")).toBeTruthy();
  expect(startWechatQRLogin).toHaveBeenCalledTimes(2);
  expect(screen.queryByText("/connect copied-to-phone")).toBeNull();
  await act(async () => {
    resolveOldPoll([]);
  });
  await act(() => rs.advanceTimersByTimeAsync(2500));
  expect(listChannelConnections).toHaveBeenCalledTimes(1);
  expect(screen.getByTitle("WeChat login QR code")).toBeTruthy();
  rs.mocked(pollWechatQRLogin).mockResolvedValue({
    ...session,
    id: "new-session",
    status: "confirmed",
    provider,
  });
  await act(() => rs.advanceTimersByTimeAsync(1500));
  await act(() => rs.advanceTimersByTimeAsync(1));
  expect(screen.getByText("/connect copied-to-phone")).toBeTruthy();
  expect(connectChannelProvider).toHaveBeenCalledTimes(1);
});

it("opens an existing WeChat configuration at binding with a route back to QR", async () => {
  rs.mocked(listChannelProviders).mockResolvedValue({
    enabled: true,
    providers: [],
  });
  rs.mocked(connectChannelProvider).mockResolvedValue({
    provider: "wechat",
    mode: "binding_code",
    code: "existing-demo",
    instruction: "Send command",
    expires_in: 600,
  });
  mountDialog(true, "binding");
  await screen.findByText("/connect existing-demo");
  expect(startWechatQRLogin).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Scan again" }));
  await screen.findByTitle("WeChat login QR code");
});

it("continues manual token saving inside the binding dialog", async () => {
  rs.mocked(listChannelProviders).mockResolvedValue({
    enabled: true,
    providers: [],
  });
  rs.mocked(connectChannelProvider).mockResolvedValue({
    provider: "wechat",
    mode: "binding_code",
    code: "manual-demo",
    instruction: "Send command",
    expires_in: 600,
  });
  const { onSubmit } = mountDialog(true);
  onSubmit.mockResolvedValue(provider);
  fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
  await screen.findByText("/connect manual-demo");
  expect(screen.getByRole("button", { name: "Scan again" })).toBeTruthy();
});

it("ignores a manual save result after the user closes the dialog", async () => {
  const { onSubmit } = mountDialog(true);
  let finish!: (provider: ChannelProvider) => void;
  onSubmit.mockImplementation(
    () =>
      new Promise<ChannelProvider>((resolve) => {
        finish = resolve;
      }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  await act(async () => {
    finish(provider);
  });
  expect(connectChannelProvider).not.toHaveBeenCalled();
  expect(screen.queryByText("Token saved securely")).toBeNull();
});
