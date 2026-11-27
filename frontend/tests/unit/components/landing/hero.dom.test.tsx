import { afterEach, describe, expect, it, rs } from "@rstest/core";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";

import { Hero } from "@/components/landing/hero";

afterEach(() => {
  cleanup();
  rs.restoreAllMocks();
});

describe("landing Hero", () => {
  it("renders a single DeerFlow h1, verified entry-point links, and the 3-tier harness blueprint", () => {
    rs.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(null, { status: 204 }),
    );

    render(<Hero />);

    const headings = screen.getAllByRole("heading", { level: 1 });
    expect(headings).toHaveLength(1);
    expect(headings[0]?.textContent).toContain("DeerFlow");

    const getStarted = screen.getByRole("link", { name: /get started/i });
    expect(getStarted.getAttribute("href")).toBe("/workspace");

    const quickStart = screen.getByRole("link", { name: /quick start/i });
    expect(quickStart.getAttribute("href")).toBe(
      "/en/docs/application/quick-start",
    );

    const docs = screen.getByRole("link", { name: /^docs$/i });
    expect(docs.getAttribute("href")).toBe("/en/docs");

    const github = screen.getByRole("link", { name: /open source/i });
    expect(github.getAttribute("href")).toBe(
      "https://github.com/bytedance/deer-flow",
    );

    const diagram = document.getElementById("architecture");
    expect(diagram).not.toBeNull();
    expect(screen.queryByText("deerflow://")).toBeNull();

    // Tier 1: Entry & Triggers
    expect(screen.getByText("Web Workspace")).toBeTruthy();
    expect(screen.getByText("IM Channels")).toBeTruthy();
    expect(screen.getByText("API & Schedules")).toBeTruthy();

    // Tier 2: LangGraph Harness Core
    expect(screen.getByText("Lead Agent Loop")).toBeTruthy();
    expect(screen.getByText("Subagent Orchestrator")).toBeTruthy();

    // Tier 3: Plug-in Execution Plane
    expect(screen.getByText("Models")).toBeTruthy();
    expect(screen.getByText("Sandboxes")).toBeTruthy();
    expect(screen.getByText("Skills")).toBeTruthy();
    expect(screen.getByText("MCP Tools")).toBeTruthy();
  });

  it("switches interactive workflow mode tabs and updates highlighted nodes and trace", () => {
    rs.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(null, { status: 204 }),
    );

    const { container } = render(<Hero />);

    const researchTab = screen.getByRole("tab", { name: "Research" });
    const sandboxTab = screen.getByRole("tab", { name: "Code & Sandbox" });
    const imBotTab = screen.getByRole("tab", { name: "IM Bot" });
    const trace = screen.getByTestId("architecture-trace");

    // Default: Research mode
    expect(researchTab.getAttribute("aria-selected")).toBe("true");
    expect(sandboxTab.getAttribute("aria-selected")).toBe("false");
    expect(trace.textContent).toContain("skill:deep-research");
    expect(
      container
        .querySelector('[data-node-id="entry-web"]')
        ?.getAttribute("data-active"),
    ).toBe("true");
    expect(
      container
        .querySelector('[data-node-id="module-mcp"]')
        ?.getAttribute("data-active"),
    ).toBe("true");
    expect(
      container
        .querySelector('[data-node-id="module-sandboxes"]')
        ?.getAttribute("data-active"),
    ).toBe("false");

    // Switch to Code & Sandbox mode
    fireEvent.click(sandboxTab);
    expect(sandboxTab.getAttribute("aria-selected")).toBe("true");
    expect(researchTab.getAttribute("aria-selected")).toBe("false");
    expect(trace.textContent).toContain("sandbox:exec tests");
    expect(
      container
        .querySelector('[data-node-id="entry-api"]')
        ?.getAttribute("data-active"),
    ).toBe("true");
    expect(
      container
        .querySelector('[data-node-id="module-sandboxes"]')
        ?.getAttribute("data-active"),
    ).toBe("true");
    expect(
      container
        .querySelector('[data-node-id="module-mcp"]')
        ?.getAttribute("data-active"),
    ).toBe("false");

    // Switch to IM Bot mode
    fireEvent.click(imBotTab);
    expect(imBotTab.getAttribute("aria-selected")).toBe("true");
    expect(trace.textContent).toContain("lark:mention");
    expect(
      container
        .querySelector('[data-node-id="entry-im"]')
        ?.getAttribute("data-active"),
    ).toBe("true");
    expect(
      container
        .querySelector('[data-node-id="engine-lead"]')
        ?.getAttribute("data-active"),
    ).toBe("true");
    expect(
      container
        .querySelector('[data-node-id="engine-subagents"]')
        ?.getAttribute("data-active"),
    ).toBe("false");
  });

  it("supports WAI-ARIA tabpanel linkage, roving tabIndex, and arrow/Home/End keyboard navigation", () => {
    rs.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(null, { status: 204 }),
    );

    render(<Hero />);

    const researchTab = screen.getByRole("tab", { name: "Research" });
    const sandboxTab = screen.getByRole("tab", { name: "Code & Sandbox" });
    const imBotTab = screen.getByRole("tab", { name: "IM Bot" });
    const panel = screen.getByRole("tabpanel");

    // Initial roving tabIndex & tabpanel linkage
    expect(researchTab.tabIndex).toBe(0);
    expect(sandboxTab.tabIndex).toBe(-1);
    expect(imBotTab.tabIndex).toBe(-1);
    expect(researchTab.getAttribute("aria-controls")).toBe(panel.id);
    expect(sandboxTab.getAttribute("aria-controls")).toBe(panel.id);
    expect(imBotTab.getAttribute("aria-controls")).toBe(panel.id);
    expect(panel.getAttribute("aria-labelledby")).toBe(researchTab.id);

    // ArrowRight moves selection and focus to Code & Sandbox
    researchTab.focus();
    fireEvent.keyDown(researchTab, { key: "ArrowRight" });
    expect(sandboxTab.getAttribute("aria-selected")).toBe("true");
    expect(sandboxTab.tabIndex).toBe(0);
    expect(researchTab.tabIndex).toBe(-1);
    expect(document.activeElement).toBe(sandboxTab);
    expect(panel.getAttribute("aria-labelledby")).toBe(sandboxTab.id);

    // End jumps to IM Bot
    fireEvent.keyDown(sandboxTab, { key: "End" });
    expect(imBotTab.getAttribute("aria-selected")).toBe("true");
    expect(document.activeElement).toBe(imBotTab);
    expect(panel.getAttribute("aria-labelledby")).toBe(imBotTab.id);

    // ArrowRight wraps around to Research
    fireEvent.keyDown(imBotTab, { key: "ArrowRight" });
    expect(researchTab.getAttribute("aria-selected")).toBe("true");
    expect(document.activeElement).toBe(researchTab);

    // ArrowLeft wraps around to IM Bot
    fireEvent.keyDown(researchTab, { key: "ArrowLeft" });
    expect(imBotTab.getAttribute("aria-selected")).toBe("true");
    expect(document.activeElement).toBe(imBotTab);

    // Home returns to Research
    fireEvent.keyDown(imBotTab, { key: "Home" });
    expect(researchTab.getAttribute("aria-selected")).toBe("true");
    expect(document.activeElement).toBe(researchTab);
    expect(panel.getAttribute("aria-labelledby")).toBe(researchTab.id);
  });

  it("inspects Tier 3 execution modules on click and clears inspection when switching modes", () => {
    rs.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(null, { status: 204 }),
    );

    render(<Hero />);

    const sandboxModule = screen.getByRole("button", { name: /sandboxes/i });
    const trace = screen.getByTestId("architecture-trace");

    expect(sandboxModule.getAttribute("aria-pressed")).toBe("false");
    fireEvent.click(sandboxModule);
    expect(sandboxModule.getAttribute("aria-pressed")).toBe("true");
    expect(trace.textContent).toContain("/mnt/user-data");

    // Switching mode clears module inspection and shows mode trace again
    fireEvent.click(screen.getByRole("tab", { name: "IM Bot" }));
    expect(sandboxModule.getAttribute("aria-pressed")).toBe("false");
    expect(trace.textContent).toContain("lark:mention");
  });

  it("renders zh-CN copy, localized docs links, and Chinese blueprint tabs", () => {
    rs.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(null, { status: 204 }),
    );

    render(<Hero locale="zh-CN" />);

    const heading = screen.getByRole("heading", { level: 1 });
    expect(heading.textContent).toContain("DeerFlow");
    expect(heading.textContent).toContain("开源超级智能体引擎");

    expect(
      screen.getByRole("link", { name: "立即开始" }).getAttribute("href"),
    ).toBe("/workspace");
    expect(
      screen.getByRole("link", { name: "快速上手" }).getAttribute("href"),
    ).toBe("/zh/docs/application/quick-start");
    expect(
      screen.getByRole("link", { name: "文档" }).getAttribute("href"),
    ).toBe("/zh/docs");

    const zhSandboxTab = screen.getByRole("tab", { name: "代码与沙箱" });
    fireEvent.click(zhSandboxTab);
    expect(zhSandboxTab.getAttribute("aria-selected")).toBe("true");
    expect(screen.getByTestId("architecture-trace").textContent).toContain(
      "sandbox:运行测试",
    );
  });

  it("renders live GitHub stars and forks when /github-stars returns valid counts", async () => {
    const fetchSpy = rs
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(Response.json({ stars: 42850, forks: 3640 }));

    render(<Hero />);

    await screen.findByText("42.8K+");
    expect(screen.getByText("3.6K+")).toBeTruthy();
    expect(screen.getByTestId("hero-github-metrics")).toBeTruthy();
    expect(fetchSpy).toHaveBeenCalledWith("/github-stars", {
      signal: expect.any(AbortSignal),
    });
  });

  it("hides the GitHub metrics row cleanly on 204 responses and aborts on unmount", async () => {
    rs.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(null, { status: 204 }),
    );

    render(<Hero />);

    await act(async () => {
      await Promise.resolve();
    });
    expect(screen.queryByTestId("hero-github-metrics")).toBeNull();

    cleanup();

    const pendingFetch = rs.spyOn(globalThis, "fetch").mockImplementation(
      () =>
        new Promise(() => {
          // Leave pending until unmount aborts the request.
        }),
    );
    const { unmount } = render(<Hero />);
    const signal = pendingFetch.mock.calls[0]?.[1]?.signal;
    unmount();
    expect(signal?.aborted).toBe(true);
  });

  it("renders stars without forks for backward-compatible responses and hides metrics on network error", async () => {
    rs.spyOn(globalThis, "fetch").mockResolvedValue(
      Response.json({ stars: 850 }),
    );

    render(<Hero />);

    await screen.findByText("850");
    expect(screen.getByText("GitHub Stars")).toBeTruthy();
    expect(screen.queryByText("Forks")).toBeNull();

    cleanup();

    rs.spyOn(globalThis, "fetch").mockRejectedValue(
      new Error("Network unavailable"),
    );

    render(<Hero />);

    await act(async () => {
      await Promise.resolve();
    });
    expect(screen.queryByTestId("hero-github-metrics")).toBeNull();
  });
});
