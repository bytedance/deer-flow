import { fetch, getCsrfHeaders } from "@/core/api/fetcher";

export type Wallet = { available_credits: number; reserved_credits: number };
export type LedgerEntry = {
  entry_type: string;
  credit_delta: number;
  reason: string | null;
  created_at: string;
};

export async function getWallet(): Promise<Wallet> {
  const response = await fetch("/api/billing/wallet");
  if (!response.ok) throw new Error("Unable to load wallet");
  return response.json();
}

export async function recharge(
  provider: "wechat" | "alipay",
  credits: number,
): Promise<Wallet> {
  const response = await fetch("/api/billing/recharge", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...getCsrfHeaders() },
    body: JSON.stringify({
      provider,
      credits,
      idempotency_key: crypto.randomUUID(),
    }),
  });
  if (!response.ok) throw new Error("Recharge failed");
  return response.json();
}

export async function getLedger(): Promise<LedgerEntry[]> {
  const response = await fetch("/api/billing/ledger");
  if (!response.ok) throw new Error("Unable to load ledger");
  return response.json();
}
