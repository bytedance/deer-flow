import { describe, expect, it } from "@rstest/core";
import { render, screen } from "@testing-library/react";

import { CaseStudySection } from "@/components/landing/sections/case-study-section";

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
});
