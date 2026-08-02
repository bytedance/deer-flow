"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  getLedger,
  getWallet,
  recharge,
  type LedgerEntry,
  type Wallet,
} from "@/core/billing/api";

export function WalletCard() {
  const queryClient = useQueryClient();
  const [wallet, setWallet] = useState<Wallet | null>(null);
  const [loading, setLoading] = useState(false);
  const [entries, setEntries] = useState<LedgerEntry[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void getWallet()
      .then(setWallet)
      .catch(() => setWallet(null));
    void getLedger()
      .then(setEntries)
      .catch(() => setEntries([]));
  }, []);
  const topUp = async (provider: "wechat" | "alipay") => {
    setLoading(true);
    setError(null);
    try {
      setWallet(await recharge(provider, 1000));
      await queryClient.invalidateQueries({ queryKey: ["billing", "wallet"] });
      setEntries(await getLedger());
    } catch {
      setError("充值暂时不可用，请稍后重试。");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="border-border/70 space-y-4 border-t pt-5">
      <div className="flex items-end justify-between">
        <div>
          <p className="text-sm font-medium">积分余额</p>
          <p className="text-muted-foreground text-xs">
            任务将根据实际 Token 用量扣费
          </p>
        </div>
        <p className="text-2xl font-semibold tabular-nums">
          {wallet?.available_credits ?? "—"}
        </p>
      </div>
      <div className="flex gap-2">
        <Button
          size="sm"
          disabled={loading}
          onClick={() => void topUp("wechat")}
        >
          微信充值
        </Button>
        <Button
          size="sm"
          variant="outline"
          disabled={loading}
          onClick={() => void topUp("alipay")}
        >
          支付宝充值
        </Button>
      </div>
      {error && <p className="text-destructive text-xs">{error}</p>}
      {entries.length > 0 && (
        <div className="text-muted-foreground divide-y text-xs">
          {entries.slice(0, 5).map((entry) => (
            <div
              className="flex justify-between py-2"
              key={`${entry.created_at}-${entry.entry_type}`}
            >
              <span>{entry.reason ?? entry.entry_type}</span>
              <span className="tabular-nums">
                {entry.credit_delta > 0 ? "+" : ""}
                {entry.credit_delta}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
