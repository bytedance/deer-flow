"use client";

import { useEffect, useState } from "react";

import { AdminSection } from "@/components/admin/admin-section";
import { fetch } from "@/core/api/fetcher";

type Order = {
  id: string;
  email: string;
  provider: string;
  amount_fen: number;
  credits: number;
  status: string;
  created_at: string;
};

export default function OrdersPage() {
  const [items, setItems] = useState<Order[]>([]);
  useEffect(() => {
    void fetch("/api/admin/orders")
      .then((r) => (r.ok ? (r.json() as Promise<Order[]>) : []))
      .then(setItems);
  }, []);
  return (
    <AdminSection
      title="充值订单"
      description="查看本地模拟微信、支付宝充值订单及积分到账状态；当前不会调用真实支付渠道。"
    >
      <div className="overflow-x-auto border-y">
        <table className="w-full min-w-[680px] text-left text-sm">
          <thead className="text-muted-foreground border-b text-xs">
            <tr>
              <th className="p-3">租户</th>
              <th>渠道</th>
              <th>金额</th>
              <th>积分</th>
              <th>状态</th>
              <th>时间</th>
            </tr>
          </thead>
          <tbody>
            {items.length === 0 ? (
              <tr>
                <td className="text-muted-foreground p-5" colSpan={6}>
                  暂无充值订单。
                </td>
              </tr>
            ) : (
              items.map((item) => (
                <tr className="border-b last:border-0" key={item.id}>
                  <td className="p-3">{item.email}</td>
                  <td>{item.provider === "wechat" ? "微信支付" : "支付宝"}</td>
                  <td>{(item.amount_fen / 100).toFixed(2)} 元</td>
                  <td>{item.credits}</td>
                  <td>{item.status === "paid" ? "已支付" : item.status}</td>
                  <td className="text-muted-foreground">
                    {new Date(item.created_at).toLocaleString()}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </AdminSection>
  );
}
