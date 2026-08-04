"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";

import { AdminSection } from "@/components/admin/admin-section";
import { Button } from "@/components/ui/button";
import { fetch } from "@/core/api/fetcher";

type RiskEvent = {
  id: string;
  user_id: string;
  direction: string;
  category: string;
  severity: string;
  redacted_excerpt: string;
  status: string;
  created_at: string;
};

export default function SafetyPage() {
  const [items, setItems] = useState<RiskEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [active, setActive] = useState<RiskEvent | null>(null);
  const [resolution, setResolution] = useState("false_positive");
  const [reason, setReason] = useState("");
  const load = useCallback(() => {
    void fetch("/api/admin/safety/events")
      .then(async (response) => {
        if (!response.ok) throw new Error("无法加载风险事件");
        return response.json() as Promise<{ items: RiskEvent[] }>;
      })
      .then((data) => setItems(data.items))
      .catch((cause: unknown) =>
        setError(cause instanceof Error ? cause.message : "无法加载风险事件"),
      );
  }, []);
  useEffect(() => load(), [load]);
  const resolve = async (event: FormEvent) => {
    event.preventDefault();
    if (!active) return;
    const response = await fetch(
      `/api/admin/safety/events/${active.id}/resolve`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ resolution, reason }),
      },
    );
    if (!response.ok) {
      setError("处置保存失败，请填写理由后重试。");
      return;
    }
    setActive(null);
    setReason("");
    load();
  };
  return (
    <AdminSection
      title="内容安全"
      description="只展示脱敏风险摘要。处置和受控上下文查看均必须留痕，管理员无法浏览完整聊天。"
    >
      {error ? <p className="text-destructive text-sm">{error}</p> : null}
      <div className="divide-y border-y">
        {items.length === 0 ? (
          <p className="text-muted-foreground py-6 text-sm">暂无风险事件。</p>
        ) : (
          items.map((item) => (
            <article
              className="grid gap-2 py-4 md:grid-cols-[1fr_auto]"
              key={item.id}
            >
              <div>
                <p className="font-medium">
                  {item.category} · {item.severity}
                </p>
                <p className="text-muted-foreground mt-1 text-sm">
                  {item.redacted_excerpt}
                </p>
                <p className="text-muted-foreground mt-1 text-xs">
                  租户 {item.user_id} · {item.direction} ·{" "}
                  {new Date(item.created_at).toLocaleString()}
                </p>
              </div>
              {item.status === "open" ? (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => setActive(item)}
                >
                  处置
                </Button>
              ) : (
                <span className="text-muted-foreground text-sm">已处理</span>
              )}
            </article>
          ))
        )}
      </div>
      {active ? (
        <form
          className="bg-muted/30 space-y-3 rounded-lg border p-4"
          onSubmit={resolve}
        >
          <div>
            <p className="text-sm font-medium">处置风险事件</p>
            <p className="text-muted-foreground mt-1 text-xs">
              {active.category} · {active.redacted_excerpt}
            </p>
          </div>
          <label className="text-muted-foreground block text-xs">
            处置结论
            <select
              className="text-foreground bg-background mt-1 h-8 w-full border px-2 text-sm"
              value={resolution}
              onChange={(event) => setResolution(event.target.value)}
            >
              <option value="false_positive">误判关闭</option>
              <option value="warned">已警示用户</option>
              <option value="limited">已限制任务</option>
              <option value="escalated">升级处理</option>
            </select>
          </label>
          <label className="text-muted-foreground block text-xs">
            处置理由
            <textarea
              className="text-foreground bg-background mt-1 min-h-20 w-full border p-2 text-sm"
              required
              value={reason}
              onChange={(event) => setReason(event.target.value)}
            />
          </label>
          <div className="flex gap-2">
            <Button size="sm" type="submit">
              保存处置
            </Button>
            <Button
              size="sm"
              type="button"
              variant="outline"
              onClick={() => setActive(null)}
            >
              取消
            </Button>
          </div>
        </form>
      ) : null}
    </AdminSection>
  );
}
