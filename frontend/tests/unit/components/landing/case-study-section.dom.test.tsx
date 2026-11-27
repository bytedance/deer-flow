import { afterEach, describe, expect, it } from "@rstest/core";
import { cleanup, render, screen } from "@testing-library/react";

import { CaseStudySection } from "@/components/landing/sections/case-study-section";

afterEach(cleanup);

describe("CaseStudySection", () => {
  it("uses semantic, lazy, intrinsically-sized images", () => {
    render(<CaseStudySection />);

    const images = screen.getAllByRole("img");
    expect(images).toHaveLength(6);
    for (const image of images) {
      expect(image.getAttribute("loading")).toBe("lazy");
      expect(image.getAttribute("decoding")).toBe("async");
      expect(Number(image.getAttribute("width"))).toBeGreaterThan(0);
      expect(Number(image.getAttribute("height"))).toBeGreaterThan(0);
      expect(image.getAttribute("alt")?.length).toBeGreaterThan(0);
    }

    expect(document.querySelector('[style*="background-image"]')).toBeNull();
  });

  it("sets canonical anchor id, numbered index, links to /showcase threads, and supports zh-CN copy", () => {
    const { container, rerender } = render(<CaseStudySection locale="en-US" />);

    const section = container.querySelector("section#case-studies");
    expect(section).not.toBeNull();
    expect(screen.getAllByText("01").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("Inspect replay")).toHaveLength(6);

    const links = screen.getAllByRole("link");
    expect(links).toHaveLength(6);
    for (const link of links) {
      expect(link.getAttribute("href")).toMatch(/^\/showcase\/[0-9a-f-]+$/);
    }

    rerender(<CaseStudySection locale="zh-CN" />);
    expect(screen.getByRole("heading", { level: 2 }).textContent).toBe(
      "实战案例",
    );
    expect(screen.getAllByText("查看回放")).toHaveLength(6);
  });
});
