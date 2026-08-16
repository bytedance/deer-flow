import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { ComponentProps } from "react";

import {
  GenericToolCallDetails,
  TOOL_CALL_PAYLOAD_LIMIT,
} from "@/components/workspace/messages/generic-tool-call-details";
import { I18nContext } from "@/core/i18n/context";
import { enUS } from "@/core/i18n/locales/en-US";

const clipboardMock = rs.hoisted(() => ({
  writeTextToClipboard: rs.fn().mockResolvedValue(true),
}));

rs.mock("@/core/clipboard", () => ({
  writeTextToClipboard: clipboardMock.writeTextToClipboard,
}));

afterEach(() => {
  cleanup();
  clipboardMock.writeTextToClipboard.mockClear();
  rs.restoreAllMocks();
});

describe("GenericToolCallDetails", () => {
  it("keeps payloads collapsed until requested", () => {
    renderDetails();

    expect(screen.getByRole("button", { name: "Tool details" })).toBeTruthy();
    expect(screen.queryByText("Call ID")).toBeNull();
    expect(screen.queryByText("run-123")).toBeNull();
  });

  it("does not inspect payload values before the details are expanded", () => {
    const readPayload = rs.fn(() => "large diagnostic value");
    const args: Record<string, unknown> = {};
    Object.defineProperty(args, "payload", {
      enumerable: true,
      get: readPayload,
    });

    renderDetails({ args });
    expect(readPayload).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Tool details" }));
    expect(readPayload).toHaveBeenCalledTimes(1);
  });

  it("shows bounded input, result, metadata, and copy actions", () => {
    renderDetails();

    fireEvent.click(screen.getByRole("button", { name: "Tool details" }));

    expect(screen.getByText("Call ID")).toBeTruthy();
    expect(screen.getByText("call-mcp-1")).toBeTruthy();
    expect(screen.getByText("mcp_execute")).toBeTruthy();
    expect(screen.getByText("Input")).toBeTruthy();
    expect(screen.getByText("Result")).toBeTruthy();
    expect(screen.getByText(/"run_id": "run-123"/)).toBeTruthy();
    expect(
      screen.getAllByRole("button", { name: /Copy to clipboard:/ }),
    ).toHaveLength(2);
  });

  it("labels failed tool results as errors", () => {
    renderDetails({ isError: true, result: "permission denied" });

    fireEvent.click(screen.getByRole("button", { name: "Tool details" }));

    expect(screen.getByText("Error")).toBeTruthy();
    expect(screen.queryByText("Result")).toBeNull();
  });

  it("copies only the bounded representation and its truncation marker", () => {
    renderDetails({ result: "x".repeat(100_000) });

    fireEvent.click(screen.getByRole("button", { name: "Tool details" }));
    const marker = `Truncated after ${TOOL_CALL_PAYLOAD_LIMIT.toLocaleString(
      "en-US",
    )} characters.`;
    expect(screen.getByText(marker)).toBeTruthy();

    fireEvent.click(
      screen.getByRole("button", { name: "Copy to clipboard: Result" }),
    );

    expect(clipboardMock.writeTextToClipboard).toHaveBeenCalledTimes(1);
    const copied = clipboardMock.writeTextToClipboard.mock.calls[0]?.[0] as
      | string
      | undefined;
    expect(copied).toBeDefined();
    expect(copied).toContain(marker);
    expect(copied!.length).toBeLessThan(100_000);
  });
});

function renderDetails(
  overrides: Partial<ComponentProps<typeof GenericToolCallDetails>> = {},
) {
  return render(
    <I18nContext.Provider
      value={{ locale: "en-US", setLocale: () => undefined, t: enUS }}
    >
      <GenericToolCallDetails
        toolName="mcp_execute"
        toolCallId="call-mcp-1"
        args={{ run_id: "run-123" }}
        result={{ status: "completed" }}
        {...overrides}
      />
    </I18nContext.Provider>,
  );
}
