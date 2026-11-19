import { afterEach, beforeEach, describe, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { StrictMode } from "react";

rs.mock("@/core/channels/api", () => ({
  connectChannelProvider: rs.fn(),
  listChannelProviders: rs.fn(),
  listChannelConnections: rs.fn(),
}));
rs.mock("@/core/clipboard", () => ({ writeTextToClipboard: rs.fn() }));

import { ChannelBindingCodeDialog } from "@/components/workspace/channels/channel-binding-code-dialog";
import { GatewayApiError } from "@/core/api/errors";
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
import { writeTextToClipboard } from "@/core/clipboard";
import type { Locale } from "@/core/i18n";
import { I18nContext } from "@/core/i18n/context";
import { enUS } from "@/core/i18n/locales/en-US";
import { zhCN } from "@/core/i18n/locales/zh-CN";

function provider(id = "slack", displayName = "Slack"): ChannelProvider {
  return {
    provider: id,
    display_name: displayName,
    enabled: true,
    configured: true,
    connectable: true,
    auth_mode: "binding_code",
    connection_status: "not_connected",
    credential_fields: [],
  };
}

function minted(code: string, expiresIn = 600): ChannelConnectResponse {
  return {
    provider: "slack",
    mode: "binding_code",
    url: null,
    code,
    instruction: `Send /connect ${code} to the DeerFlow Slack bot.`,
    expires_in: expiresIn,
  };
}

function gatewayError(status: number, detail: string) {
  return new GatewayApiError({
    message: detail,
    status,
    code: null,
    params: {},
    rawMessage: detail,
  });
}

beforeEach(() => {
  rs.mocked(listChannelProviders).mockResolvedValue({
    enabled: true,
    providers: [],
  });
  rs.mocked(listChannelConnections).mockResolvedValue([]);
  rs.mocked(connectChannelProvider).mockResolvedValue(minted("abc123"));
  rs.mocked(writeTextToClipboard).mockResolvedValue(true);
});
afterEach(() => {
  cleanup();
  rs.useRealTimers();
  rs.resetAllMocks();
});

function mount(target = provider(), locale: Locale = "en-US") {
  const onOpenChange = rs.fn();
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const view = (current: ChannelProvider) => (
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        <I18nContext.Provider
          value={{
            locale,
            setLocale: () => undefined,
            t: locale === "zh-CN" ? zhCN : enUS,
          }}
        >
          <ChannelBindingCodeDialog
            provider={current}
            open
            onOpenChange={onOpenChange}
          />
        </I18nContext.Provider>
      </QueryClientProvider>
    </StrictMode>
  );
  const { rerender } = render(view(target));
  return {
    onOpenChange,
    rerender: (next: ChannelProvider) => rerender(view(next)),
  };
}

describe("ChannelBindingCodeDialog", () => {
  it("keeps the command on screen and copies it", async () => {
    const { rerender } = mount();
    expect(await screen.findByText("/connect abc123")).toBeTruthy();
    expect(screen.getByRole("dialog", { name: "Connect Slack" })).toBeTruthy();
    expect(
      screen.getByText(
        "Send this command to the Slack bot to link it to your DeerFlow account.",
      ),
    ).toBeTruthy();
    expect(screen.getByText("Waiting for your message in Slack…")).toBeTruthy();
    // The server's English sentence is no longer shown.
    expect(screen.queryByText(/DeerFlow Slack bot/)).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Copy command" }));
    expect(await screen.findByRole("button", { name: "Copied" })).toBeTruthy();
    expect(writeTextToClipboard).toHaveBeenCalledExactlyOnceWith(
      "/connect abc123",
    );

    // A refreshed provider list re-renders the dialog with the same code.
    rerender({ ...provider() });
    expect(screen.getByText("/connect abc123")).toBeTruthy();
    expect(connectChannelProvider).toHaveBeenCalledExactlyOnceWith("slack");
  });

  it("says so when copying fails, leaving the command selectable", async () => {
    rs.mocked(writeTextToClipboard).mockResolvedValue(false);
    mount();
    fireEvent.click(
      await screen.findByRole("button", { name: "Copy command" }),
    );
    expect(
      await screen.findByText(
        "Could not copy. Select and copy the command above.",
      ),
    ).toBeTruthy();
    expect(screen.getByText("/connect abc123")).toBeTruthy();
  });

  it("shows when the code expires in the UI language's time format", async () => {
    rs.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "Date"] });
    rs.setSystemTime(new Date(2026, 9, 26, 9, 0));
    mount();
    await act(() => rs.advanceTimersByTimeAsync(1));
    const tenMinutesLater = new Intl.DateTimeFormat("en-US", {
      hour: "2-digit",
      minute: "2-digit",
    }).format(new Date(2026, 9, 26, 9, 10));
    expect(screen.getByText(`Expires at ${tenMinutesLater}`)).toBeTruthy();
  });

  it("shows the connection once the bot reports it", async () => {
    rs.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "Date"] });
    const { onOpenChange } = mount();
    await act(() => rs.advanceTimersByTimeAsync(1));
    expect(screen.getByText("/connect abc123")).toBeTruthy();

    rs.mocked(listChannelConnections).mockResolvedValue([
      { provider: "slack", status: "connected" } as ChannelConnection,
    ]);
    await act(() => rs.advanceTimersByTimeAsync(2000));
    expect(screen.getByText("Slack is connected")).toBeTruthy();
    expect(screen.queryByText("/connect abc123")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(onOpenChange).toHaveBeenCalledExactlyOnceWith(false);
  });

  it("offers a new code once the old one expires", async () => {
    rs.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "Date"] });
    rs.mocked(connectChannelProvider)
      .mockResolvedValueOnce(minted("first"))
      .mockResolvedValueOnce(minted("second"));
    mount();
    await act(() => rs.advanceTimersByTimeAsync(1));
    expect(screen.getByText("/connect first")).toBeTruthy();

    await act(() => rs.advanceTimersByTimeAsync(600_000));
    expect(screen.getByText("This binding code has expired.")).toBeTruthy();
    expect(screen.queryByText("/connect first")).toBeNull();

    fireEvent.click(
      screen.getByRole("button", { name: "Generate a new code" }),
    );
    await act(() => rs.advanceTimersByTimeAsync(1));
    expect(screen.getByText("/connect second")).toBeTruthy();
    expect(connectChannelProvider).toHaveBeenCalledTimes(2);
  });

  it("explains the unused-code limit instead of the server's English detail", async () => {
    const detail =
      "Too many pending channel connection codes. Wait for existing codes to expire or use one of them.";
    rs.mocked(connectChannelProvider).mockRejectedValueOnce(
      gatewayError(429, detail),
    );
    mount();
    expect(
      await screen.findByText(
        "Too many unused codes. Use a code you already have or wait about 10 minutes for them to expire.",
      ),
    ).toBeTruthy();
    expect(screen.queryByText(detail)).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("/connect abc123")).toBeTruthy();
    expect(connectChannelProvider).toHaveBeenCalledTimes(2);
  });

  it("keeps the server's reason for other failures", async () => {
    rs.mocked(connectChannelProvider).mockRejectedValueOnce(
      gatewayError(400, "Channel provider is not configured"),
    );
    mount();
    expect(
      await screen.findByText("Could not create a binding code."),
    ).toBeTruthy();
    expect(screen.getByText("Channel provider is not configured")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Try again" })).toBeTruthy();
  });

  it.each([
    {
      target: provider("feishu", "Feishu"),
      title: "连接飞书",
      sentence: "把下面这条命令发给飞书机器人，即可绑定到你的 DeerFlow 账号。",
    },
    {
      target: provider(),
      title: "连接 Slack",
      sentence:
        "把下面这条命令发给 Slack 机器人，即可绑定到你的 DeerFlow 账号。",
    },
  ])(
    "speaks Chinese in a Chinese UI ($title)",
    async ({ target, title, sentence }) => {
      rs.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "Date"] });
      rs.setSystemTime(new Date(2026, 9, 26, 9, 0));
      mount(target, "zh-CN");
      await act(() => rs.advanceTimersByTimeAsync(1));
      expect(screen.getByRole("dialog", { name: title })).toBeTruthy();
      expect(screen.getByText(sentence)).toBeTruthy();
      expect(screen.getByRole("button", { name: "复制命令" })).toBeTruthy();
      expect(screen.getByText("09:10 过期")).toBeTruthy();
    },
  );
});
