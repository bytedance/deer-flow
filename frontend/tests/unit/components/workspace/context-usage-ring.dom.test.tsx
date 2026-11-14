import { afterEach, describe, expect, it, rs } from "@rstest/core";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";

import { ContextUsageRing } from "@/components/workspace/context-usage-ring";
import type { ContextUsageBreakdown } from "@/core/threads/token-usage";

rs.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({
    locale: "en-US",
    t: {
      contextUsage: {
        breakdownTitle: "Context composition",
        ringAriaLabel: (percentage: string) =>
          `Context composition, ${percentage}% of the window used`,
        ringAriaLabelNoWindow: (tokens: string) =>
          `Context composition, ${tokens} ${tokens === "1" ? "token" : "tokens"} used`,
        ringAriaLabelEmpty: "Context composition, no data yet",
        usedOfWindow: (used: string, total: string) =>
          `${used} of ${total} used`,
        usedOnly: (used: string) =>
          `${used} ${used === "1" ? "token" : "tokens"} used`,
        remaining: (remaining: string) => `${remaining} remaining`,
        shareOfWindow: "Share of the context window",
        shareOfUsed: "Share of the tokens used",
        empty:
          "No composition data yet. Send a message and it will be captured.",
        categories: {
          systemPrompt: "System prompt",
          tools: "Tools",
          skills: "Skills",
          memoryContext: "Memory & context",
          conversation: "Conversation",
        },
        subcategories: {
          builtinTools: "Built-in",
          mcpTools: "MCP",
          memory: "Memory",
          taskState: "Task state",
          otherInjection: "System extras",
          conversationMessages: "Messages",
          toolResults: "Tool results",
        },
      },
    },
  }),
}));

const BREAKDOWN: ContextUsageBreakdown = {
  totalTokens: 1000,
  percentage: 10,
  remainingTokens: 9000,
  systemPromptTokens: 100,
  builtinToolsTokens: 200,
  mcpToolsTokens: 50,
  skillBodyTokens: 25,
  memoryTokens: 30,
  taskStateTokens: 40,
  otherInjectionTokens: 5,
  conversationTokens: 500,
  toolResultTokens: 50,
  modelName: "offline",
  contextWindow: 10000,
  capturedAt: "2026-11-12T00:00:00Z",
};

afterEach(() => {
  cleanup();
});

function ringTrigger() {
  return screen.getByTestId("context-usage-ring");
}

function circles() {
  return ringTrigger().querySelectorAll("circle");
}

async function openPopover() {
  fireEvent.click(ringTrigger());
  return screen.findByTestId("context-usage-popover");
}

describe("ContextUsageRing", () => {
  it("renders the neutral placeholder before a snapshot exists", async () => {
    const onOpen = rs.fn();
    render(<ContextUsageRing breakdown={null} onOpen={onOpen} />);

    expect(ringTrigger().dataset.contextUsageState).toBe("empty");
    expect(ringTrigger().getAttribute("aria-label")).toBe(
      "Context composition, no data yet",
    );
    expect(circles()).toHaveLength(1);
    expect(circles()[0]?.getAttribute("stroke-dasharray")).toBe("2 3");
    // Without a known window the placeholder stays light.
    expect(circles()[0]?.getAttribute("class")).toContain("text-border");
    expect(ringTrigger().querySelector("svg")?.getAttribute("class")).toContain(
      "size-3.5",
    );

    const popover = await openPopover();
    expect(popover.getAttribute("aria-label")).toBe("Context composition");
    expect(popover.className).toContain("data-[state=open]:animate-in");
    expect(
      within(popover).getByText(
        "No composition data yet. Send a message and it will be captured.",
      ),
    ).toBeTruthy();
    expect(onOpen).toHaveBeenCalledTimes(1);
  });

  it("keeps a solid light track before a snapshot when the model declares a window", () => {
    render(<ContextUsageRing breakdown={null} contextWindow={4000} />);

    expect(ringTrigger().dataset.contextUsageState).toBe("empty");
    expect(circles()).toHaveLength(1);
    expect(circles()[0]?.getAttribute("stroke-dasharray")).toBeNull();
    expect(circles()[0]?.getAttribute("class")).toContain("text-border");
  });

  it("keeps the dashed track light before a snapshot when the model declares no window", () => {
    render(<ContextUsageRing breakdown={null} contextWindow={null} />);

    expect(ringTrigger().dataset.contextUsageState).toBe("empty");
    expect(circles()).toHaveLength(1);
    expect(circles()[0]?.getAttribute("stroke-dasharray")).toBe("2 3");
    expect(circles()[0]?.getAttribute("class")).toContain("text-border");
  });

  it("shows window-relative shares and the remaining space", async () => {
    const onOpen = rs.fn();
    render(<ContextUsageRing breakdown={BREAKDOWN} onOpen={onOpen} />);

    expect(ringTrigger().dataset.contextUsageState).toBe("window");
    expect(ringTrigger().getAttribute("aria-label")).toBe(
      "Context composition, 10% of the window used",
    );
    // A solid track plus the filled arc.
    expect(circles()).toHaveLength(2);
    expect(circles()[0]?.getAttribute("stroke-dasharray")).toBeNull();
    expect(circles()[0]?.getAttribute("class")).toContain("text-border");

    const popover = await openPopover();
    expect(within(popover).getByText("1.0K of 10.0K used")).toBeTruthy();
    expect(within(popover).getByText("10%")).toBeTruthy();
    expect(
      within(popover).getByText("Share of the context window"),
    ).toBeTruthy();
    expect(within(popover).getByText("9.0K remaining")).toBeTruthy();
    expect(within(popover).getByText("System prompt")).toBeTruthy();
    expect(within(popover).getByText("100 · 1%")).toBeTruthy();
    expect(within(popover).getByText("250 · 2.5%")).toBeTruthy();
    expect(within(popover).getByText("550 · 5.5%")).toBeTruthy();
    expect(within(popover).getByText("offline")).toBeTruthy();
    expect(onOpen).toHaveBeenCalledTimes(1);
  });

  it("shares of used tokens when the model declares no window", async () => {
    const onOpen = rs.fn();
    render(
      <ContextUsageRing
        breakdown={{ ...BREAKDOWN, contextWindow: null, percentage: null }}
        onOpen={onOpen}
      />,
    );

    expect(ringTrigger().dataset.contextUsageState).toBe("used-only");
    expect(ringTrigger().getAttribute("aria-label")).toBe(
      "Context composition, 1.0K tokens used",
    );
    expect(circles()).toHaveLength(1);
    expect(circles()[0]?.getAttribute("stroke-dasharray")).toBe("2 3");
    expect(circles()[0]?.getAttribute("class")).toContain("text-primary");

    const popover = await openPopover();
    expect(within(popover).getByText("1.0K tokens used")).toBeTruthy();
    expect(within(popover).getByText("Share of the tokens used")).toBeTruthy();
    expect(within(popover).queryByText(/remaining$/)).toBeNull();
    expect(within(popover).getByText("100 · 10%")).toBeTruthy();
    expect(within(popover).getByText("250 · 25%")).toBeTruthy();
    expect(within(popover).getByText("550 · 55%")).toBeTruthy();
    expect(onOpen).toHaveBeenCalledTimes(1);
  });

  it("draws no arc while a declared window is still empty", async () => {
    render(
      <ContextUsageRing
        breakdown={{
          ...BREAKDOWN,
          totalTokens: 0,
          percentage: 0,
          remainingTokens: 10000,
          systemPromptTokens: 0,
          builtinToolsTokens: 0,
          mcpToolsTokens: 0,
          skillBodyTokens: 0,
          memoryTokens: 0,
          taskStateTokens: 0,
          otherInjectionTokens: 0,
          conversationTokens: 0,
          toolResultTokens: 0,
        }}
      />,
    );

    expect(ringTrigger().dataset.contextUsageState).toBe("window");
    expect(ringTrigger().getAttribute("aria-label")).toBe(
      "Context composition, 0% of the window used",
    );
    expect(circles()).toHaveLength(1);

    const popover = await openPopover();
    expect(within(popover).getByText("0 of 10.0K used")).toBeTruthy();
    expect(within(popover).getByText("10.0K remaining")).toBeTruthy();
  });

  it("expands and collapses grouped rows", async () => {
    render(<ContextUsageRing breakdown={BREAKDOWN} />);
    const popover = await openPopover();

    const tools = within(popover).getByRole("button", { name: /Tools/ });
    expect(tools.getAttribute("aria-expanded")).toBe("false");
    expect(within(popover).queryByText("Built-in")).toBeNull();

    fireEvent.click(tools);
    expect(tools.getAttribute("aria-expanded")).toBe("true");
    expect(within(popover).getByText("Built-in")).toBeTruthy();
    expect(within(popover).getByText("MCP")).toBeTruthy();

    fireEvent.click(tools);
    expect(tools.getAttribute("aria-expanded")).toBe("false");
    expect(within(popover).queryByText("Built-in")).toBeNull();
  });

  it("keeps the chevron beside the label and every number right-aligned", async () => {
    render(<ContextUsageRing breakdown={BREAKDOWN} />);
    const popover = await openPopover();

    // A leaf row has no chevron, and its number is the last item.
    const systemRow = within(popover).getByText("System prompt").closest("div");
    expect(systemRow?.querySelector("svg")).toBeNull();
    expect(systemRow?.lastElementChild?.textContent).toBe("100 · 1%");

    // An expandable row puts the chevron right after the label, so the number
    // still ends at the same right edge.
    const tools = within(popover).getByRole("button", { name: /Tools/ });
    const toolsLabel = within(tools).getByText("Tools");
    expect(toolsLabel.nextElementSibling?.tagName.toLowerCase()).toBe("svg");
    expect(toolsLabel.nextElementSibling?.getAttribute("class")).toContain(
      "size-3",
    );
    expect(tools.lastElementChild?.textContent).toBe("250 · 2.5%");
  });

  it("draws a minimum visible arc for tiny window usage", () => {
    render(
      <ContextUsageRing
        breakdown={{ ...BREAKDOWN, totalTokens: 1, percentage: 0.01 }}
      />,
    );

    expect(circles()).toHaveLength(2);
    const arcLength = Number.parseFloat(
      circles()[1]?.getAttribute("stroke-dasharray") ?? "",
    );
    // About 12° of the 16px ring, not the true sub-pixel share.
    expect(arcLength).toBeGreaterThan(1.4);
    expect(arcLength).toBeCloseTo((12 / 360) * 2 * Math.PI * 7, 2);
    expect(ringTrigger().getAttribute("aria-label")).toBe(
      "Context composition, <0.1% of the window used",
    );
  });

  it("clamps a request that exceeds the window to a full arc", async () => {
    render(
      <ContextUsageRing
        breakdown={{
          ...BREAKDOWN,
          totalTokens: 12_000,
          percentage: 120,
          remainingTokens: 0,
        }}
      />,
    );

    expect(circles()).toHaveLength(2);
    const arcLength = Number.parseFloat(
      circles()[1]?.getAttribute("stroke-dasharray") ?? "",
    );
    expect(arcLength).toBeCloseTo(2 * Math.PI * 7, 2);

    const popover = await openPopover();
    expect(within(popover).getByText("120%")).toBeTruthy();
  });

  it("follows the selected model's window without waiting for a new snapshot", () => {
    const { rerender } = render(
      <ContextUsageRing breakdown={BREAKDOWN} contextWindow={null} />,
    );
    expect(ringTrigger().dataset.contextUsageState).toBe("used-only");
    expect(circles()).toHaveLength(1);
    expect(circles()[0]?.getAttribute("class")).toContain("text-primary");

    rerender(<ContextUsageRing breakdown={BREAKDOWN} contextWindow={4000} />);
    expect(ringTrigger().dataset.contextUsageState).toBe("window");
    expect(ringTrigger().getAttribute("aria-label")).toBe(
      "Context composition, 25% of the window used",
    );
    expect(circles()).toHaveLength(2);
    expect(circles()[0]?.getAttribute("class")).toContain("text-border");

    rerender(<ContextUsageRing breakdown={BREAKDOWN} contextWindow={null} />);
    expect(ringTrigger().dataset.contextUsageState).toBe("used-only");
    expect(circles()).toHaveLength(1);
  });

  it("shows the window of the selected model when the snapshot has none", async () => {
    render(
      <ContextUsageRing
        breakdown={{ ...BREAKDOWN, contextWindow: null, percentage: null }}
        contextWindow={10000}
      />,
    );

    expect(ringTrigger().dataset.contextUsageState).toBe("window");
    expect(ringTrigger().getAttribute("aria-label")).toBe(
      "Context composition, 10% of the window used",
    );

    const popover = await openPopover();
    expect(within(popover).getByText("1.0K of 10.0K used")).toBeTruthy();
    expect(within(popover).getByText("9.0K remaining")).toBeTruthy();
  });

  it("labels the popover with the selected model", async () => {
    render(
      <ContextUsageRing breakdown={BREAKDOWN} modelName="selected-model" />,
    );

    const popover = await openPopover();
    expect(within(popover).getByText("selected-model")).toBeTruthy();
    expect(within(popover).queryByText("offline")).toBeNull();
  });
});
