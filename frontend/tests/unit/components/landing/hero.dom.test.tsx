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
  it("renders a single DeerFlow h1, verified entry-point links, and the deerflow:// architecture diagram", () => {
    rs.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(null, { status: 204 }),
    );

    render(<Hero />);

    const headings = screen.getAllByRole("heading", { level: 1 });
    expect(headings).toHaveLength(1);
    expect(headings[0]?.textContent).toContain("DeerFlow");

    const getStarted = screen.getByRole("link", { name: /get started/i });
    expect(getStarted.getAttribute("href")).toBe("/workspace/chats/new");

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

    expect(document.getElementById("architecture")).not.toBeNull();
    expect(screen.getAllByText("deerflow://").length).toBeGreaterThan(0);
    expect(screen.getAllByText("models/").length).toBeGreaterThan(0);
    expect(screen.getAllByText("sandbox/").length).toBeGreaterThan(0);
    expect(screen.getAllByText("skills/").length).toBeGreaterThan(0);
    expect(screen.getAllByText("mcp/").length).toBeGreaterThan(0);
    expect(screen.getAllByText("memory/").length).toBeGreaterThan(0);
    expect(screen.getAllByText("channels/").length).toBeGreaterThan(0);
  });

  it("renders zh-CN copy and localized docs links", () => {
    rs.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(null, { status: 204 }),
    );

    render(<Hero locale="zh-CN" />);

    const heading = screen.getByRole("heading", { level: 1 });
    expect(heading.textContent).toContain("DeerFlow");
    expect(heading.textContent).toContain("开源超级智能体引擎");

    expect(
      screen.getByRole("link", { name: "立即开始" }).getAttribute("href"),
    ).toBe("/workspace/chats/new");
    expect(
      screen.getByRole("link", { name: "快速上手" }).getAttribute("href"),
    ).toBe("/zh/docs/application/quick-start");
    expect(
      screen.getByRole("link", { name: "文档" }).getAttribute("href"),
    ).toBe("/zh/docs");
    expect(screen.getAllByText("多模型路由与工具调用").length).toBeGreaterThan(
      0,
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

  it("toggles active capability highlighting interactively in the architecture diagram", () => {
    rs.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(null, { status: 204 }),
    );

    render(<Hero />);

    const sandboxButtons = screen.getAllByRole("button", { name: /sandbox/i });
    const target = sandboxButtons[0];
    expect(target).toBeDefined();
    expect(target?.getAttribute("aria-pressed")).toBe("false");

    if (target) {
      fireEvent.click(target);
      expect(target.getAttribute("aria-pressed")).toBe("true");
      fireEvent.click(target);
      expect(target.getAttribute("aria-pressed")).toBe("false");
    }
  });
});
