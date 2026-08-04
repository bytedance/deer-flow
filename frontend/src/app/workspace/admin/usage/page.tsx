"use client";

import { useEffect, useState } from "react";

import { AdminSection } from "@/components/admin/admin-section";
import { Button } from "@/components/ui/button";
import { fetch } from "@/core/api/fetcher";

type Usage = {
  email: string;
  run_id: string;
  model_name: string;
  input_tokens: number;
  output_tokens: number;
  charged_credits: number;
  created_at: string;
};

export default function UsagePage() {
  const [items, setItems] = useState<Usage[]>([]);
  useEffect(() => {
    void fetch("/api/admin/usage")
      .then((r) => (r.ok ? (r.json() as Promise<Usage[]>) : []))
      .then(setItems);
  }, []);
  const exportCsv = () => {
    const header = [
      "租户",
      "任务",
      "模型",
      "输入Token",
      "输出Token",
      "扣减积分",
      "时间",
    ];
    const quote = (value: string | number) =>
      `"${String(value).replaceAll('"', '""')}"`;
    const csv = [
      header,
      ...items.map((item) => [
        item.email,
        item.run_id,
        item.model_name,
        item.input_tokens,
        item.output_tokens,
        item.charged_credits,
        item.created_at,
      ]),
    ]
      .map((row) => row.map(quote).join(","))
      .join("\n");
    const url = URL.createObjectURL(
      new Blob([`\uFEFF${csv}`], { type: "text/csv;charset=utf-8" }),
    );
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "deerflow-usage.csv";
    anchor.click();
    URL.revokeObjectURL(url);
  };
  return (
    <AdminSection
      title="用量账单"
      description="按租户、模型和任务查看实际 Token 用量与已扣积分。"
    >
      <div>
        <Button
          size="sm"
          variant="outline"
          onClick={exportCsv}
          disabled={items.length === 0}
        >
          导出当前账单 CSV
        </Button>
      </div>
      <div className="overflow-x-auto border-y">
        <table className="w-full min-w-[720px] text-left text-sm">
          <thead className="text-muted-foreground border-b text-xs">
            <tr>
              <th className="p-3">租户</th>
              <th>模型</th>
              <th>输入 / 输出 Token</th>
              <th>扣减积分</th>
              <th>时间</th>
            </tr>
          </thead>
          <tbody>
            {items.length === 0 ? (
              <tr>
                <td className="text-muted-foreground p-5" colSpan={5}>
                  暂无已结算用量。
                </td>
              </tr>
            ) : (
              items.map((item) => (
                <tr
                  className="border-b last:border-0"
                  key={`${item.run_id}-${item.model_name}`}
                >
                  <td className="p-3">{item.email}</td>
                  <td>{item.model_name}</td>
                  <td className="tabular-nums">
                    {item.input_tokens} / {item.output_tokens}
                  </td>
                  <td className="tabular-nums">{item.charged_credits}</td>
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
