import type { Message } from "@langchain/langgraph-sdk";
import { afterEach, beforeEach, expect, it, rs } from "@rstest/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useState, type ButtonHTMLAttributes, type ReactNode } from "react";

const counts = rs.hoisted(() => ({ button: 0 }));

rs.mock("@/components/ui/button", () => ({
  Button: ({
    children,
    ...props
  }: ButtonHTMLAttributes<HTMLButtonElement> & { children?: ReactNode }) => {
    counts.button += 1;
    return <button {...props}>{children}</button>;
  },
}));

import { ToolCallDetails } from "@/components/workspace/messages/tool-call-details";
import { I18nProvider } from "@/core/i18n/context";

const args = { query: "deer-flow" };

function result(content: string) {
  return {
    id: `tool-${content}`,
    type: "tool",
    tool_call_id: "call-1",
    content,
  } as unknown as Message;
}

function Parent({ resultMessage }: { resultMessage?: Message }) {
  const [, setTick] = useState(0);
  return (
    <>
      <button type="button" onClick={() => setTick((value) => value + 1)}>
        rerender
      </button>
      <ToolCallDetails
        name="lookup"
        callId="call-1"
        args={args}
        resultMessage={resultMessage}
      />
    </>
  );
}

function mount(resultMessage?: Message) {
  return render(
    <I18nProvider initialLocale="en-US">
      <Parent resultMessage={resultMessage} />
    </I18nProvider>,
  );
}

beforeEach(() => {
  counts.button = 0;
});
afterEach(cleanup);

it("does not re-render unchanged tool details when the parent re-renders", () => {
  const { rerender } = mount(result("done"));
  fireEvent.click(screen.getByRole("button", { name: /Tool details/ }));
  const opened = counts.button;
  expect(opened).toBeGreaterThan(1);

  fireEvent.click(screen.getByRole("button", { name: "rerender" }));
  expect(counts.button).toBe(opened);

  rerender(
    <I18nProvider initialLocale="en-US">
      <Parent resultMessage={result("changed")} />
    </I18nProvider>,
  );
  expect(counts.button).toBeGreaterThan(opened);
});
