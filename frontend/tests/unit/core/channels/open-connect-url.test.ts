import { afterEach, describe, expect, test, vi } from "vitest";

import {
  closeConnectWindow,
  openConnectUrl,
  prepareConnectWindow,
} from "@/core/channels/open-connect-url";

type PopupStub = {
  closed: boolean;
  close: ReturnType<typeof vi.fn>;
  location: {
    replace: ReturnType<typeof vi.fn>;
  };
  opener: unknown;
};

function stubWindow(openResult: PopupStub | null) {
  const assign = vi.fn();
  const open = vi.fn(() => openResult);
  vi.stubGlobal("window", {
    open,
    location: { assign },
  });
  return { assign, open };
}

function makePopup(): PopupStub {
  return {
    closed: false,
    close: vi.fn(),
    location: { replace: vi.fn() },
    opener: {},
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("channel connect window helpers", () => {
  test("opens a blank tab synchronously and detaches opener", () => {
    const popup = makePopup();
    const { open } = stubWindow(popup);

    const prepared = prepareConnectWindow();

    expect(open).toHaveBeenCalledWith("about:blank", "_blank");
    expect(prepared).toBe(popup);
    expect(popup.opener).toBeNull();
  });

  test("navigates a prepared popup without opening another window", () => {
    const popup = makePopup();
    const { assign, open } = stubWindow(null);

    openConnectUrl(
      "https://t.me/deerflow_bot?start=state",
      popup as unknown as Window,
    );

    expect(open).not.toHaveBeenCalled();
    expect(assign).not.toHaveBeenCalled();
    expect(popup.location.replace).toHaveBeenCalledWith(
      "https://t.me/deerflow_bot?start=state",
    );
  });

  test("falls back to current-window navigation when no popup is available", () => {
    const { assign } = stubWindow(null);

    openConnectUrl("https://t.me/deerflow_bot?start=state");

    expect(assign).toHaveBeenCalledWith(
      "https://t.me/deerflow_bot?start=state",
    );
  });

  test("closes a prepared popup on connect failure", () => {
    const popup = makePopup();

    closeConnectWindow(popup as unknown as Window);

    expect(popup.close).toHaveBeenCalled();
  });
});
