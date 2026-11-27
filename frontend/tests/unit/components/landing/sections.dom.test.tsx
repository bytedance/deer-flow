import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { Section } from "@/components/landing/section";
import { CommunitySection } from "@/components/landing/sections/community-section";
import { SandboxSection } from "@/components/landing/sections/sandbox-section";
import { SkillsSection } from "@/components/landing/sections/skills-section";
import { WhatsNewSection } from "@/components/landing/sections/whats-new-section";

afterEach(() => {
  cleanup();
  rs.restoreAllMocks();
});

describe("Landing Section shell & content sections", () => {
  it("Section renders numbered editorial split heading without gradient text or nested main landmark", () => {
    const { container } = render(
      <Section
        id="test-sec"
        index="01"
        eyebrow="EYEBROW"
        title="Editorial Heading"
        subtitle="Concise subtitle"
        variant="soft"
      >
        <p>Section content</p>
      </Section>,
    );

    const section = container.querySelector("section#test-sec");
    expect(section).not.toBeNull();
    expect(section?.className).toContain("--df-bg-soft");
    expect(container.querySelector("main")).toBeNull();
    expect(screen.getByText("01")).toBeDefined();
    expect(screen.getByText("EYEBROW")).toBeDefined();

    const heading = screen.getByRole("heading", { level: 2 });
    expect(heading.textContent).toBe("Editorial Heading");
    expect(heading.className).not.toContain("bg-clip-text");
    expect(heading.className).not.toContain("text-transparent");
  });

  it("SkillsSection renders 3-step progression rail, interactive 2-pane skill inspector, and zh-CN copy", () => {
    const { container, rerender } = render(<SkillsSection locale="en-US" />);

    expect(container.querySelector("section#skills")).not.toBeNull();
    expect(screen.getByText("/mnt/skills/")).toBeDefined();
    expect(
      screen.getByRole("button", { name: /01 Discover Manifest/i }),
    ).toBeDefined();
    expect(
      screen.getByRole("button", { name: /02 Load On-Demand/i }),
    ).toBeDefined();

    const executeStep = screen.getByRole("button", {
      name: /03 Execute in Sandbox/i,
    });
    fireEvent.click(executeStep);
    expect(
      screen.getByText("/mnt/user-data/outputs/sandbox-brief.md"),
    ).toBeDefined();

    const dataSkillButton = screen.getByRole("button", {
      name: /data-analysis/i,
    });
    fireEvent.click(dataSkillButton);
    expect(
      screen.getByText("/mnt/user-data/outputs/churn-analysis.html"),
    ).toBeDefined();
    expect(
      screen.getByText("/mnt/skills/data-analysis/SKILL.md"),
    ).toBeDefined();

    const resetButton = screen.getByRole("button", { name: "Reset" });
    fireEvent.click(resetButton);
    expect(
      screen.getByText("/mnt/skills/deep-research/SKILL.md"),
    ).toBeDefined();

    rerender(<SkillsSection locale="zh-CN" />);
    expect(screen.getByRole("heading", { level: 2 }).textContent).toContain(
      "智能体技能",
    );
  });

  it("SkillsSection disables autoplay truthfully under prefers-reduced-motion while keeping manual controls interactive", () => {
    rs.spyOn(window, "matchMedia").mockImplementation((query: string) => ({
      matches: query === "(prefers-reduced-motion: reduce)",
      media: query,
      onchange: null,
      addListener: rs.fn(),
      removeListener: rs.fn(),
      addEventListener: rs.fn(),
      removeEventListener: rs.fn(),
      dispatchEvent: rs.fn(),
    }));

    render(<SkillsSection locale="en-US" />);

    const playButton = screen.getByRole<HTMLButtonElement>("button", {
      name: /autoplay disabled when reduced motion is preferred/i,
    });
    expect(playButton.disabled).toBe(true);
    expect(playButton.textContent).toContain("Play");

    // Clicking the disabled autoplay button never flips it into a stuck Pause state
    fireEvent.click(playButton);
    expect(screen.queryByRole("button", { name: /^pause$/i })).toBeNull();
    expect(playButton.textContent).toContain("Play");

    // Manual step selection, skill selection, and Reset remain fully interactive
    const discoverStep = screen.getByRole("button", {
      name: /01 Discover Manifest/i,
    });
    fireEvent.click(discoverStep);
    expect(discoverStep.getAttribute("aria-pressed")).toBe("true");
    expect(
      screen.getByText(
        "Select step 02 to inject the full SKILL.md instructions.",
      ),
    ).toBeDefined();

    const executeStep = screen.getByRole("button", {
      name: /03 Execute in Sandbox/i,
    });
    fireEvent.click(executeStep);
    expect(
      screen.getByText("/mnt/user-data/outputs/sandbox-brief.md"),
    ).toBeDefined();

    fireEvent.click(screen.getByRole("button", { name: /slide-deck/i }));
    expect(
      screen.getByText("/mnt/user-data/outputs/q3-architecture.pptx"),
    ).toBeDefined();

    fireEvent.click(screen.getByRole("button", { name: "Reset" }));
    expect(
      screen.getByText("/mnt/skills/deep-research/SKILL.md"),
    ).toBeDefined();
  });

  it("SandboxSection renders mount topology, backend pills, interactive console tabs, and zh-CN copy", () => {
    const { container, rerender } = render(<SandboxSection locale="en-US" />);

    expect(container.querySelector("section#sandbox")).not.toBeNull();
    expect(screen.getByText("/mnt/user-data/uploads")).toBeDefined();
    expect(screen.getByText("/mnt/user-data/outputs")).toBeDefined();
    expect(screen.getByText("Local")).toBeDefined();
    expect(screen.getByText("Docker")).toBeDefined();
    expect(screen.getByText("Kubernetes")).toBeDefined();
    expect(screen.getByText("cat requirements.txt")).toBeDefined();

    const buildTab = screen.getByRole("tab", { name: "build-and-test" });
    const dataTab = screen.getByRole("tab", { name: "data-pipeline" });
    const panel = screen.getByRole("tabpanel");

    expect(buildTab.tabIndex).toBe(0);
    expect(dataTab.tabIndex).toBe(-1);
    expect(buildTab.getAttribute("aria-controls")).toBe(panel.id);
    expect(dataTab.getAttribute("aria-controls")).toBe(panel.id);
    expect(panel.getAttribute("aria-labelledby")).toBe(buildTab.id);

    // Keyboard navigation updates selection, focus, tabpanel linkage, and terminal content
    buildTab.focus();
    fireEvent.keyDown(buildTab, { key: "ArrowRight" });
    expect(dataTab.getAttribute("aria-selected")).toBe("true");
    expect(dataTab.tabIndex).toBe(0);
    expect(buildTab.tabIndex).toBe(-1);
    expect(document.activeElement).toBe(dataTab);
    expect(panel.getAttribute("aria-labelledby")).toBe(dataTab.id);
    expect(screen.getByText("Downloaded 12.4 MB (148,290 rows)")).toBeDefined();

    fireEvent.keyDown(dataTab, { key: "Home" });
    expect(buildTab.getAttribute("aria-selected")).toBe("true");
    expect(document.activeElement).toBe(buildTab);
    expect(panel.getAttribute("aria-labelledby")).toBe(buildTab.id);

    fireEvent.keyDown(buildTab, { key: "End" });
    expect(dataTab.getAttribute("aria-selected")).toBe("true");
    expect(document.activeElement).toBe(dataTab);

    fireEvent.keyDown(dataTab, { key: "ArrowLeft" });
    expect(buildTab.getAttribute("aria-selected")).toBe("true");
    expect(document.activeElement).toBe(buildTab);

    fireEvent.click(dataTab);
    expect(screen.getByText("Downloaded 12.4 MB (148,290 rows)")).toBeDefined();

    const aioLinks = screen.getAllByRole("link", { name: /Sandbox/i });
    expect(
      aioLinks.some(
        (link) =>
          link.getAttribute("href") ===
          "https://github.com/agent-infra/sandbox",
      ),
    ).toBe(true);

    rerender(<SandboxSection locale="zh-CN" />);
    expect(screen.getByRole("heading", { level: 2 }).textContent).toBe(
      "智能体运行时沙箱",
    );
  });

  it("WhatsNewSection renders asymmetric editorial bento with 6 cards and localized docs links", () => {
    const { container, rerender } = render(<WhatsNewSection locale="en-US" />);

    expect(container.querySelector("section#whats-new")).not.toBeNull();
    expect(container.querySelector(".magic-bento-card")).toBeNull();

    const articles = container.querySelectorAll("article");
    expect(articles).toHaveLength(6);
    expect(articles[0]?.className).toContain("lg:col-span-6");
    expect(articles[1]?.className).toContain("lg:col-span-6");
    expect(articles[2]?.className).toContain("lg:col-span-3");

    const memoryLink = screen.getByRole("link", { name: "Memory docs" });
    expect(memoryLink.getAttribute("href")).toBe("/en/docs/harness/memory");

    rerender(<WhatsNewSection locale="zh-CN" />);
    const zhMemoryLink = screen.getByRole("link", { name: "记忆文档" });
    expect(zhMemoryLink.getAttribute("href")).toBe("/zh/docs/harness/memory");
  });

  it("CommunitySection renders split editorial invitation frame and spec rows without AuroraText or ambilight", () => {
    const { container, rerender } = render(<CommunitySection locale="en-US" />);

    expect(container.querySelector("section#community")).not.toBeNull();
    expect(container.querySelector(".ambilight")).toBeNull();
    expect(screen.getByRole("heading", { level: 2 }).textContent).toBe(
      "Build the open agent stack with us.",
    );
    expect(screen.getByText("MIT Open Source")).toBeDefined();
    expect(screen.getByText("LangGraph + Extensible Hooks")).toBeDefined();
    expect(screen.getByText("Web · Lark · Slack · Telegram")).toBeDefined();

    expect(
      screen.getByRole("link", { name: "Join on GitHub" }).getAttribute("href"),
    ).toBe("https://github.com/bytedance/deer-flow");
    expect(
      screen.getByRole("link", { name: "Discussions" }).getAttribute("href"),
    ).toBe("https://github.com/bytedance/deer-flow/discussions");
    expect(
      screen.getByRole("link", { name: "Documentation" }).getAttribute("href"),
    ).toBe("/en/docs");
    expect(
      screen.getByRole("link", { name: "Open Workspace" }).getAttribute("href"),
    ).toBe("/workspace");

    rerender(<CommunitySection locale="zh-CN" />);
    expect(screen.getByRole("heading", { level: 2 }).textContent).toBe(
      "共建开源智能体基础设施",
    );
    expect(
      screen.getByRole("link", { name: "阅读文档" }).getAttribute("href"),
    ).toBe("/zh/docs");
  });
});
