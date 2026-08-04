"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";

import { AdminSection } from "@/components/admin/admin-section";
import { Button } from "@/components/ui/button";
import { fetch } from "@/core/api/fetcher";
import { useModels } from "@/core/models/hooks";

type Policy = {
  id: string;
  model_name: string;
  input_fen_per_million: number;
  output_fen_per_million: number;
  cache_read_fen_per_million: number | null;
  credit_multiplier_bps: number;
  max_reservation_credits: number;
  active: boolean;
};
const blank = {
  model_name: "",
  input_fen_per_million: "0",
  output_fen_per_million: "0",
  cache_read_fen_per_million: "",
  credit_multiplier_bps: "10000",
  max_reservation_credits: "100",
};

export default function BillingPage() {
  const { models } = useModels();
  const [items, setItems] = useState<Policy[]>([]);
  const [draft, setDraft] = useState(blank);
  const [notice, setNotice] = useState<string | null>(null);
  const load = useCallback(() => {
    void fetch("/api/admin/model-pricing")
      .then((r) => (r.ok ? (r.json() as Promise<Policy[]>) : []))
      .then(setItems);
  }, []);
  useEffect(() => load(), [load]);
  const save = async (event: FormEvent) => {
    event.preventDefault();
    const response = await fetch("/api/admin/model-pricing", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ...draft,
        input_fen_per_million: Number(draft.input_fen_per_million),
        output_fen_per_million: Number(draft.output_fen_per_million),
        cache_read_fen_per_million: draft.cache_read_fen_per_million
          ? Number(draft.cache_read_fen_per_million)
          : null,
        credit_multiplier_bps: Number(draft.credit_multiplier_bps),
        max_reservation_credits: Number(draft.max_reservation_credits),
      }),
    });
    setNotice(
      response.ok
        ? "策略已保存并记录审计日志。"
        : "保存失败，请检查模型和数值。",
    );
    if (response.ok) {
      setDraft(blank);
      load();
    }
  };
  const input = (label: string, key: keyof typeof blank, min = "0") => (
    <label className="text-muted-foreground text-xs">
      {label}
      <input
        className="text-foreground mt-1 h-8 w-full border bg-transparent px-2 text-sm"
        min={min}
        required={key !== "cache_read_fen_per_million"}
        type="number"
        value={draft[key]}
        onChange={(event) =>
          setDraft((value) => ({ ...value, [key]: event.target.value }))
        }
      />
    </label>
  );
  return (
    <AdminSection
      title="计费与模型"
      description="每个可选模型拥有独立的价格、积分倍率与任务预占额度；同一模型只启用最新策略。"
    >
      {notice ? <p className="text-sm">{notice}</p> : null}
      <form className="grid gap-3 border-y py-4 md:grid-cols-3" onSubmit={save}>
        <label className="text-muted-foreground text-xs">
          模型名称
          <select
            className="text-foreground mt-1 h-8 w-full border bg-transparent px-2 text-sm"
            required
            value={draft.model_name}
            onChange={(event) =>
              setDraft((value) => ({
                ...value,
                model_name: event.target.value,
              }))
            }
          >
            <option value="" disabled>
              选择已配置模型
            </option>
            {models.map((model) => (
              <option key={model.name} value={model.name}>
                {model.display_name || model.name}
              </option>
            ))}
          </select>
        </label>
        {input("输入价格（分/百万 Token）", "input_fen_per_million")}
        {input("输出价格（分/百万 Token）", "output_fen_per_million")}
        {input("缓存价格（分/百万 Token）", "cache_read_fen_per_million")}
        {input("积分倍率（10000=1:1）", "credit_multiplier_bps", "1")}
        {input("任务预占积分", "max_reservation_credits", "1")}
        <div className="flex items-end">
          <Button size="sm" type="submit">
            保存策略
          </Button>
        </div>
      </form>
      <div className="divide-y border-y">
        {items.map((item) => (
          <article
            className="flex flex-wrap justify-between gap-2 py-3 text-sm"
            key={item.id}
          >
            <span className="font-medium">
              {item.model_name} {!item.active ? "（历史版本）" : ""}
            </span>
            <span className="text-muted-foreground">
              输入 {item.input_fen_per_million} 分 · 输出{" "}
              {item.output_fen_per_million} 分 · 倍率{" "}
              {item.credit_multiplier_bps} · 预占 {item.max_reservation_credits}{" "}
              积分
            </span>
          </article>
        ))}
      </div>
    </AdminSection>
  );
}
