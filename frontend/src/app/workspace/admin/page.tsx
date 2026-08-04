"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { fetch } from "@/core/api/fetcher";

const modules = [
  {
    href: "/workspace/admin/tenants",
    title: "租户与用户",
    description: "管理独立租户、积分余额和账号冻结状态。",
  },
  {
    href: "/workspace/admin/billing",
    title: "计费与模型",
    description: "维护模型价格、积分倍率和任务预占额度。",
  },
  {
    href: "/workspace/admin/usage",
    title: "用量账单",
    description: "查看实际 Token 用量和积分结算记录。",
  },
  {
    href: "/workspace/admin/orders",
    title: "充值订单",
    description: "核对模拟微信、支付宝充值和积分到账。",
  },
  {
    href: "/workspace/admin/skills",
    title: "技能市场",
    description: "发布版本化技能，供租户主动安装。",
  },
  {
    href: "/workspace/admin/safety",
    title: "内容安全",
    description: "审查脱敏风险事件并处置违规内容。",
  },
  {
    href: "/workspace/admin/audit",
    title: "审计日志",
    description: "查看管理员操作及安全处置的留痕。",
  },
];
type Overview = {
  tenant_count: number;
  available_credits: number;
  today_recharge_credits: number;
  today_consumption_credits: number;
  open_risk_events: number;
};

export default function AdminPage() {
  const [overview, setOverview] = useState<Overview | null>(null);
  useEffect(() => {
    void fetch("/api/admin/overview")
      .then((response) =>
        response.ok ? (response.json() as Promise<Overview>) : null,
      )
      .then(setOverview);
  }, []);
  const metrics = overview
    ? [
        { label: "租户数", value: overview.tenant_count },
        { label: "可用积分", value: overview.available_credits },
        { label: "今日充值", value: overview.today_recharge_credits },
        { label: "今日消耗", value: overview.today_consumption_credits },
        { label: "待处理风险", value: overview.open_risk_events },
      ]
    : [];
  return (
    <section className="space-y-8">
      <header className="border-b pb-6">
        <p className="text-muted-foreground text-sm">
          平台状态、租户、计费与安全运营
        </p>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight">运营概览</h1>
      </header>
      {metrics.length > 0 ? (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
          {metrics.map((metric) => (
            <article
              className="bg-background rounded-lg border p-4"
              key={metric.label}
            >
              <p className="text-muted-foreground text-xs">{metric.label}</p>
              <p className="mt-2 text-2xl font-semibold tabular-nums">
                {metric.value}
              </p>
            </article>
          ))}
        </div>
      ) : null}
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {modules.map((module) => (
          <Link
            className="group bg-background hover:border-primary hover:bg-muted/40 rounded-lg border p-5 transition-colors"
            href={module.href}
            key={module.href}
          >
            <h2 className="group-hover:text-primary font-semibold">
              {module.title}
            </h2>
            <p className="text-muted-foreground mt-2 text-sm leading-6">
              {module.description}
            </p>
            <span className="mt-4 inline-block text-sm font-medium">
              进入管理 →
            </span>
          </Link>
        ))}
      </div>
    </section>
  );
}
