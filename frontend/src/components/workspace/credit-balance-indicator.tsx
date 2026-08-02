"use client";

import { useQuery } from "@tanstack/react-query";
import { CoinsIcon } from "lucide-react";

import { getWallet } from "@/core/billing/api";

export function CreditBalanceIndicator() {
  const { data: wallet } = useQuery({
    queryKey: ["billing", "wallet"],
    queryFn: getWallet,
    staleTime: 0,
    refetchOnWindowFocus: true,
  });

  if (!wallet) return null;

  return (
    <div className="text-muted-foreground bg-background/70 flex h-auto items-center gap-1.5 rounded-full border px-2 py-1 text-xs font-normal">
      <CoinsIcon size={14} />
      <span>可用积分</span>
      <span className="font-mono">
        {wallet.available_credits.toLocaleString()} 积分
      </span>
    </div>
  );
}
