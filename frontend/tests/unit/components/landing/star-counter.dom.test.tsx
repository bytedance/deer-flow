import { afterEach, describe, expect, it, rs } from "@rstest/core";
import { act, cleanup, render, screen } from "@testing-library/react";

import { StarCounter } from "@/components/landing/star-counter";

rs.mock("@/components/ui/number-ticker", () => ({
  NumberTicker: ({ value }: { value: number }) => <span>{value}</span>,
}));

afterEach(() => {
  cleanup();
  rs.restoreAllMocks();
});

describe("landing star counter", () => {
  it("loads the runtime count without sending a GitHub token from the browser", async () => {
    const fetch = rs
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(Response.json({ stars: 43210 }));
    render(<StarCounter />);
    await screen.findByText("43210");
    expect(fetch).toHaveBeenCalledWith("/github-stars", {
      signal: expect.any(AbortSignal),
    });
  });

  it("keeps the count hidden when the runtime reports no available count", async () => {
    rs.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(null, { status: 204 }),
    );
    const { container } = render(<StarCounter />);
    await act(async () => {
      await Promise.resolve();
    });
    expect(container.textContent).toBe("");
  });

  it("keeps the count hidden when the frontend endpoint is unreachable", async () => {
    rs.spyOn(globalThis, "fetch").mockRejectedValue(
      new Error("Network unavailable"),
    );
    const { container } = render(<StarCounter />);
    await act(async () => {
      await Promise.resolve();
    });
    expect(container.textContent).toBe("");
  });

  it("cancels the request when the header unmounts", () => {
    const fetch = rs.spyOn(globalThis, "fetch").mockImplementation(
      () =>
        new Promise(() => {
          // Keep the request pending until the component cancels it.
        }),
    );
    const { unmount } = render(<StarCounter />);
    const signal = fetch.mock.calls[0]?.[1]?.signal;
    unmount();
    expect(signal?.aborted).toBe(true);
  });
});
