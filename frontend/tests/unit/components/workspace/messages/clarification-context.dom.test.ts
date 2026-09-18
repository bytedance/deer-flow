import type { Message } from "@langchain/langgraph-sdk";
import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { createElement, type ComponentProps } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { MessageGroup } from "@/components/workspace/messages/message-group";
import { I18nContext } from "@/core/i18n/context";
import { enUS } from "@/core/i18n/locales/en-US";

const artifactsMockState = rs.hoisted(() => ({
  autoOpen: false,
  autoSelect: false,
}));

rs.mock("@/components/workspace/artifacts", () => ({
  useArtifacts: () => ({
    artifacts: [],
    setArtifacts: () => undefined,
    selectedArtifact: null,
    autoSelect: artifactsMockState.autoSelect,
    select: () => undefined,
    deselect: () => undefined,
    open: false,
    autoOpen: artifactsMockState.autoOpen,
    setOpen: () => undefined,
  }),
}));

afterEach(() => {
  artifactsMockState.autoOpen = false;
  artifactsMockState.autoSelect = false;
  rs.restoreAllMocks();
});

describe("Clarification context", () => {
  it("renders clarification context once outside the processing panel, including mixed tool calls", () => {
    for (const mixed of [false, true]) {
      const html = renderGroup([
        {
          id: "ask",
          type: "ai",
          content: "Completed deployment plan.",
          additional_kwargs: {
            reasoning_content: "Choose the deployment target.",
          },
          tool_calls: [
            ...(mixed
              ? [
                  {
                    id: "search",
                    name: "web_search",
                    args: { query: "deployment" },
                  },
                ]
              : []),
            {
              id: "clarify",
              name: "ask_clarification",
              args: { question: "Which environment?" },
            },
          ],
        } as Message,
      ]);
      const root = document.createElement("div");
      root.innerHTML = html;
      const panel = root.querySelector(".border");
      expect(panel).not.toBeNull();
      expect(panel?.textContent).not.toContain("Completed deployment plan.");
      expect(
        root.textContent?.split("Completed deployment plan."),
      ).toHaveLength(2);
      expect(panel?.textContent).toContain("Need your help");
    }
  });
});

function renderGroup(
  messages: Message[],
  props: Omit<ComponentProps<typeof MessageGroup>, "messages"> = {},
) {
  return renderToStaticMarkup(
    createElement(
      I18nContext.Provider,
      {
        value: {
          locale: "en-US",
          setLocale: () => undefined,
          t: enUS,
        },
      },
      createElement(MessageGroup, { ...props, messages }),
    ),
  );
}
