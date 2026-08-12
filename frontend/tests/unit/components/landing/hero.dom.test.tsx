import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { act, cleanup, render, screen } from "@testing-library/react";

import { Hero } from "@/components/landing/hero";

class MediaQueryListMock {
  matches = false;
  addEventListener = rs.fn();
  removeEventListener = rs.fn();

  constructor(matches: boolean) {
    this.matches = matches;
  }
}

function stubReducedMotion(matches: boolean) {
  rs.stubGlobal(
    "matchMedia",
    rs.fn(
      (query: string) =>
        new MediaQueryListMock(matches && query.includes("reduced-motion")),
    ),
  );
}

afterEach(() => {
  cleanup();
  rs.restoreAllMocks();
  rs.useRealTimers();
});

describe("Hero", () => {
  it("hides the rotating headline from assistive technology", () => {
    stubReducedMotion(false);
    render(<Hero />);

    // `AuroraText` renders its own `sr-only` copy of the word, and
    // `AnimatePresence` keeps the outgoing word mounted during the
    // cross-fade — two headline texts would otherwise be announced at once.
    const rotating = screen.getByText("Deep Research", {
      selector: ".sr-only",
    });
    expect(rotating.closest('[aria-hidden="true"]')).not.toBeNull();
  });

  it("keeps SuperAgent as the line's stable semantic text", () => {
    stubReducedMotion(false);
    render(<Hero />);

    const stable = screen.getByText("SuperAgent");
    expect(stable.closest('[aria-hidden="true"]')).toBeNull();
  });

  it("rotates words by default", () => {
    rs.useFakeTimers();
    stubReducedMotion(false);
    render(<Hero />);

    expect(screen.queryAllByText("Deep Research").length).toBeGreaterThan(0);

    act(() => {
      rs.advanceTimersByTime(2200);
    });

    // Guards the test below: proves the fake-timer plumbing really does drive
    // the rotation, so a green "stops rotating" result means something.
    expect(screen.queryAllByText("Collect Data").length).toBeGreaterThan(0);
  });

  it("stops rotating words when reduced motion is requested", () => {
    rs.useFakeTimers();
    stubReducedMotion(true);
    render(<Hero />);

    expect(screen.queryAllByText("Deep Research").length).toBeGreaterThan(0);

    act(() => {
      rs.advanceTimersByTime(10_000);
    });

    // Still the first word, and no later word ever reached the DOM: the
    // rotation interval is never installed. Checking every other word matters
    // because `AnimatePresence` leaves outgoing nodes mounted, so asserting
    // only that the first word is still present would pass either way.
    expect(screen.queryAllByText("Deep Research").length).toBeGreaterThan(0);
    for (const word of [
      "Collect Data",
      "Analyze Data",
      "Generate Webpages",
      "Vibe Coding",
      "Generate Slides",
    ]) {
      expect(screen.queryAllByText(word)).toHaveLength(0);
    }
  });
});
