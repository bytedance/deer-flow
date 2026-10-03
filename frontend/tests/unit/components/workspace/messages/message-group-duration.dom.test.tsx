import type { Message } from "@langchain/langgraph-sdk";
import { afterEach, expect, it, rs } from "@rstest/core";
import { cleanup, render, screen } from "@testing-library/react";

import { MessageGroup } from "@/components/workspace/messages/message-group";
import { I18nContext } from "@/core/i18n/context";
import { enUS } from "@/core/i18n/locales/en-US";

rs.mock("@/components/workspace/artifacts", () => ({
  useArtifacts: () => ({ artifacts: [], autoOpen: false, autoSelect: false }),
}));
afterEach(cleanup);

it("updates a memoized reasoning header when only its duration changes", () => {
  const messages: Message[] = [
    {
      id: "reasoning",
      type: "ai",
      content: "",
      additional_kwargs: { reasoning_content: "Consider the question." },
    },
  ];
  const view = (durationSeconds: number) => (
    <I18nContext.Provider
      value={{ locale: "en-US", setLocale: () => undefined, t: enUS }}
    >
      <MessageGroup messages={messages} durationSeconds={durationSeconds} />
    </I18nContext.Provider>
  );
  const { rerender } = render(view(31));
  expect(
    screen.getByRole("button", { name: "Took 31s Reasoning" }),
  ).toBeTruthy();
  rerender(view(47));
  expect(
    screen.getByRole("button", { name: "Took 47s Reasoning" }),
  ).toBeTruthy();
  expect(
    screen.queryByRole("button", { name: "Took 31s Reasoning" }),
  ).toBeNull();
  expect(screen.getAllByTestId("run-duration")).toHaveLength(1);
});
