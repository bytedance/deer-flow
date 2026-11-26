import { afterEach, describe, expect, it } from "@rstest/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { Section } from "@/components/landing/section";
import { CommunitySection } from "@/components/landing/sections/community-section";
import { SandboxSection } from "@/components/landing/sections/sandbox-section";
import { SkillsSection } from "@/components/landing/sections/skills-section";
import { WhatsNewSection } from "@/components/landing/sections/whats-new-section";

afterEach(cleanup);

describe("Landing Section shell & content sections", () => {
  it("Section renders editorial heading without gradient text or nested main landmark", () => {
    const { container } = render(
      <Section
        id="test-sec"
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

    const heading = screen.getByRole("heading", { level: 2 });
    expect(heading.textContent).toBe("Editorial Heading");
    expect(heading.className).not.toContain("bg-clip-text");
    expect(heading.className).not.toContain("text-transparent");
  });

  it("SkillsSection renders anchor id, interactive stages, and zh-CN copy", () => {
    const { container, rerender } = render(<SkillsSection locale="en-US" />);

    expect(container.querySelector("section#skills")).not.toBeNull();
    expect(screen.getByText("/mnt/skills/")).toBeDefined();

    const deployButton = screen.getByRole("button", { name: "04 Deploy" });
    fireEvent.click(deployButton);
    expect(
      screen.getByText("Live at biotech-startup.vercel.app"),
    ).toBeDefined();

    rerender(<SkillsSection locale="zh-CN" />);
    expect(screen.getByRole("heading", { level: 2 }).textContent).toContain(
      "智能体技能",
    );
  });

  it("SandboxSection switches terminal scenes, links AIO Sandbox, and supports zh-CN", () => {
    const { container, rerender } = render(<SandboxSection locale="en-US" />);

    expect(container.querySelector("section#sandbox")).not.toBeNull();
    expect(screen.getByText("cat requirements.txt")).toBeDefined();

    const dataTab = screen.getByRole("tab", { name: "data-pipeline" });
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

  it("WhatsNewSection renders 6 editorial cards without MagicBento and localizes docs links", () => {
    const { container, rerender } = render(<WhatsNewSection locale="en-US" />);

    expect(container.querySelector("section#whats-new")).not.toBeNull();
    expect(container.querySelector(".magic-bento-card")).toBeNull();
    expect(container.querySelectorAll("article")).toHaveLength(6);

    const memoryLink = screen.getByRole("link", { name: "Memory docs" });
    expect(memoryLink.getAttribute("href")).toBe("/en/docs/harness/memory");

    rerender(<WhatsNewSection locale="zh-CN" />);
    const zhMemoryLink = screen.getByRole("link", { name: "记忆文档" });
    expect(zhMemoryLink.getAttribute("href")).toBe("/zh/docs/harness/memory");
  });

  it("CommunitySection renders 3-cell highlights and CTAs without AuroraText or ambilight", () => {
    const { container, rerender } = render(<CommunitySection locale="en-US" />);

    expect(container.querySelector("section#community")).not.toBeNull();
    expect(container.querySelector(".ambilight")).toBeNull();
    expect(screen.getByText("MIT")).toBeDefined();
    expect(screen.getByText("2.0")).toBeDefined();
    expect(screen.getByText("100%")).toBeDefined();

    expect(
      screen.getByRole("link", { name: "Join on GitHub" }).getAttribute("href"),
    ).toBe("https://github.com/bytedance/deer-flow");
    expect(
      screen.getByRole("link", { name: "Documentation" }).getAttribute("href"),
    ).toBe("/en/docs");
    expect(
      screen.getByRole("link", { name: "Open Workspace" }).getAttribute("href"),
    ).toBe("/workspace");

    rerender(<CommunitySection locale="zh-CN" />);
    expect(
      screen.getByRole("link", { name: "阅读文档" }).getAttribute("href"),
    ).toBe("/zh/docs");
  });
});
