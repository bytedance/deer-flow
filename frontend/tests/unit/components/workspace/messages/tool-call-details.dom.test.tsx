import type { Message } from "@langchain/langgraph-sdk";
import { afterEach, describe, expect, it, rs } from "@rstest/core";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";

import { MessageGroup } from "@/components/workspace/messages/message-group";
import { I18nContext } from "@/core/i18n/context";
import { enUS } from "@/core/i18n/locales/en-US";

rs.mock("@/components/workspace/artifacts", () => ({
  useArtifacts: () => ({ setOpen: () => undefined, select: () => undefined }),
}));
afterEach(() => {
  cleanup();
  rs.restoreAllMocks();
});

const call: Message = {
  type: "ai",
  id: "ai",
  content: "",
  tool_calls: [
    { id: "call-1", name: "mcp_lookup", args: { query: "example" } },
  ],
};
function tool(
  content: string,
  status: "success" | "error" = "success",
): Message {
  return {
    type: "tool",
    id: `tool-${content}`,
    tool_call_id: "call-1",
    content,
    status,
  };
}
function group(messages: Message[], debug = true) {
  return (
    <I18nContext.Provider
      value={{ locale: "en-US", setLocale: () => undefined, t: enUS }}
    >
      <MessageGroup messages={messages} showTokenDebugSummaries={debug} />
    </I18nContext.Provider>
  );
}
function expand() {
  fireEvent.click(screen.getByRole("button", { name: "Tool details" }));
}

describe("generic tool details", () => {
  it("uses Debug without token statistics and does no payload work while collapsed", () => {
    const args = {
      get query() {
        throw new Error("collapsed payload was read");
      },
    };
    const messages: Message[] = [
      {
        ...call,
        tool_calls: [{ id: "call-1", name: "mcp_lookup", args }],
      } as Message,
    ];
    const { rerender } = render(group(messages, false));
    expect(screen.queryByRole("button", { name: "Tool details" })).toBeNull();
    rerender(group(messages));
    expect(
      screen
        .getByRole("button", { name: "Tool details" })
        .getAttribute("aria-expanded"),
    ).toBe("false");
    expect(screen.queryByRole("region", { name: "Input" })).toBeNull();
  });
  it("matches the first nonempty result and its error status by call ID", () => {
    render(
      group([
        tool(""),
        tool('{"reason":"denied"}', "error"),
        call,
        tool("later result"),
      ]),
    );
    expand();
    expect(screen.getByRole("region", { name: "Error" }).textContent).toContain(
      "denied",
    );
    expect(
      screen.getByRole("region", { name: "Call ID" }).textContent,
    ).toContain("call-1");
    expect(screen.queryByText("later result")).toBeNull();
  });
  it("distinguishes missing, empty and falsy results during updates", () => {
    const { rerender } = render(group([call]));
    expand();
    expect(screen.getByText("No result received")).toBeTruthy();
    rerender(group([call, tool("")]));
    expect(screen.getByText("Empty result")).toBeTruthy();
    for (const content of ["null", "false", "0"]) {
      rerender(group([call, tool(content)]));
      expect(
        screen.getByRole("region", { name: "Result" }).querySelector("pre")
          ?.textContent,
      ).toBe(content);
    }
  });
  it("copies exactly the bounded preview and reports clipboard failures", async () => {
    const writeText = rs.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
    render(group([call, tool("x".repeat(20000))]));
    expand();
    const result = screen.getByRole("region", { name: "Result" });
    expect(within(result).getByText(enUS.toolCalls.truncated)).toBeTruthy();
    fireEvent.click(within(result).getByRole("button"));
    await waitFor(() =>
      expect(writeText).toHaveBeenCalledWith(
        result.querySelector("pre")?.textContent,
      ),
    );
    writeText.mockRejectedValue(new Error("denied"));
    fireEvent.click(within(result).getByRole("button"));
    await waitFor(() =>
      expect(within(result).getByRole("status").textContent).toBe(
        enUS.clipboard.failedToCopyToClipboard,
      ),
    );
  });
  it("keeps specialized tools unchanged and resets disclosure when Debug is disabled", () => {
    const { rerender } = render(group([call, tool("hello")]));
    expand();
    rerender(group([call], false));
    expect(screen.queryByRole("region", { name: "Input" })).toBeNull();
    rerender(group([call]));
    expect(
      screen
        .getByRole("button", { name: "Tool details" })
        .getAttribute("aria-expanded"),
    ).toBe("false");
    rerender(
      group([
        {
          ...call,
          tool_calls: [
            { id: "call-1", name: "web_search", args: { query: "example" } },
          ],
        } as Message,
      ]),
    );
    expect(screen.queryByRole("button", { name: "Tool details" })).toBeNull();
  });
});
