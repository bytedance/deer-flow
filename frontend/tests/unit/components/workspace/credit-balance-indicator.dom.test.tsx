import { describe, expect, it, rs } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";

rs.mock("@/core/billing/api", () => ({
  getWallet: rs.fn(async () => ({
    available_credits: 1000,
    reserved_credits: 0,
  })),
}));

describe("CreditBalanceIndicator", () => {
  it("shows the current user's available credits", async () => {
    const { CreditBalanceIndicator } =
      await import("@/components/workspace/credit-balance-indicator");

    render(
      <QueryClientProvider client={new QueryClient()}>
        <CreditBalanceIndicator />
      </QueryClientProvider>,
    );

    expect(await screen.findByText("1,000 积分")).toBeTruthy();
  });
});
