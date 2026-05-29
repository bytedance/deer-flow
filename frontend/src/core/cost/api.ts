import { fetchGateway } from "@/core/api";

export interface BudgetStatus {
  daily_cost: number;
  daily_limit: number;
  daily_remaining: number;
  daily_pct: number;
  monthly_cost: number;
  monthly_limit: number;
  monthly_remaining: number;
  monthly_pct: number;
  is_exceeded: boolean;
  alert_triggered: boolean;
}

export async function getBudgetStatus(): Promise<BudgetStatus> {
  const res = await fetchGateway("/api/cost/budget");
  if (!res.ok) {
    throw new Error(`Failed to fetch budget status: ${res.statusText}`);
  }
  return res.json();
}
