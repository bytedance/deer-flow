"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import { fetch } from "@/core/api/fetcher";
import { useAuth } from "@/core/auth/AuthProvider";
import { useModels } from "@/core/models/hooks";

type UserRow = {
  id: string;
  email: string;
  system_role: string;
  is_frozen: boolean;
  available_credits: number;
};
type UsageRow = {
  email: string;
  run_id: string;
  model_name: string;
  input_tokens: number;
  output_tokens: number;
  charged_credits: number;
  created_at: string;
};
type PricePolicy = {
  id: string;
  model_name: string;
  input_fen_per_million: number;
  output_fen_per_million: number;
  cache_read_fen_per_million: number | null;
  credit_multiplier_bps: number;
  max_reservation_credits: number;
  active: boolean;
};

const emptyPolicy = {
  model_name: "",
  input_fen_per_million: "0",
  output_fen_per_million: "0",
  cache_read_fen_per_million: "",
  credit_multiplier_bps: "10000",
  max_reservation_credits: "100",
};

export default function AdminPage() {
  const { user } = useAuth();
  const { models } = useModels();
  const [users, setUsers] = useState<UserRow[]>([]);
  const [usage, setUsage] = useState<UsageRow[]>([]);
  const [policies, setPolicies] = useState<PricePolicy[]>([]);
  const [policy, setPolicy] = useState(emptyPolicy);
  const [notice, setNotice] = useState<string | null>(null);
  const load = useCallback(() => {
    void fetch("/api/admin/users")
      .then((r) => (r.ok ? r.json() : []))
      .then(setUsers);
    void fetch("/api/admin/usage")
      .then((r) => (r.ok ? r.json() : []))
      .then(setUsage);
    void fetch("/api/admin/model-pricing")
      .then((r) => (r.ok ? r.json() : []))
      .then(setPolicies);
  }, []);
  useEffect(() => {
    if (user?.system_role === "admin") load();
  }, [load, user?.system_role]);
  const adjust = async (id: string) => {
    const raw = window.prompt("输入要增减的积分（负数为扣减）", "100");
    if (!raw) return;
    const credits = Number(raw);
    const reason = window.prompt("填写调整原因", "管理员调整") ?? "管理员调整";
    const response = await fetch(`/api/admin/users/${id}/credits`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ credits, reason }),
    });
    setNotice(response.ok ? "积分已调整" : "积分调整失败：余额不足或输入无效");
    if (response.ok) load();
  };
  const toggleFreeze = async (item: UserRow) => {
    const response = await fetch(
      `/api/admin/users/${item.id}/freeze?frozen=${!item.is_frozen}`,
      { method: "POST" },
    );
    setNotice(
      response.ok
        ? item.is_frozen
          ? "账号已恢复"
          : "账号已冻结"
        : "账号状态更新失败",
    );
    if (response.ok) load();
  };
  const savePolicy = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const response = await fetch("/api/admin/model-pricing", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model_name: policy.model_name,
        input_fen_per_million: Number(policy.input_fen_per_million),
        output_fen_per_million: Number(policy.output_fen_per_million),
        cache_read_fen_per_million:
          policy.cache_read_fen_per_million === ""
            ? null
            : Number(policy.cache_read_fen_per_million),
        credit_multiplier_bps: Number(policy.credit_multiplier_bps),
        max_reservation_credits: Number(policy.max_reservation_credits),
      }),
    });
    setNotice(
      response.ok ? "模型计费策略已保存" : "计费策略保存失败，请检查填写的数值",
    );
    if (response.ok) {
      setPolicy(emptyPolicy);
      load();
    }
  };
  if (user?.system_role !== "admin")
    return (
      <WorkspaceContainer>
        <WorkspaceHeader title="无权访问" />
        <WorkspaceBody>仅管理员可以查看运营后台。</WorkspaceBody>
      </WorkspaceContainer>
    );
  return (
    <WorkspaceContainer>
      <WorkspaceHeader title="运营后台" />
      <WorkspaceBody>
        <div className="space-y-8">
          <div>
            <h2 className="text-lg font-semibold">用户与积分</h2>
            <p className="text-muted-foreground text-sm">
              查看余额、调整积分或冻结账号；所有操作会保留在积分账本中。
            </p>
          </div>
          {notice && <p className="text-sm">{notice}</p>}
          <div className="divide-y border-y">
            {users.map((item) => (
              <div
                className="flex items-center justify-between gap-4 py-3 text-sm"
                key={item.id}
              >
                <div>
                  <p className="font-medium">{item.email}</p>
                  <p className="text-muted-foreground">
                    {item.is_frozen ? "已冻结" : "正常"} · {item.system_role}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <p className="tabular-nums">{item.available_credits} 积分</p>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => void adjust(item.id)}
                  >
                    调积分
                  </Button>
                  <Button
                    size="sm"
                    variant={item.is_frozen ? "outline" : "destructive"}
                    onClick={() => void toggleFreeze(item)}
                  >
                    {item.is_frozen ? "恢复" : "冻结"}
                  </Button>
                </div>
              </div>
            ))}
          </div>
          <div>
            <h2 className="text-lg font-semibold">模型计费策略</h2>
            <p className="text-muted-foreground mb-3 text-sm">
              模型来源与对话模型选择保持一致；每个模型只有一条当前生效策略，更新后会保留历史版本。
            </p>
            <form
              className="grid gap-2 border-y py-3 md:grid-cols-3"
              onSubmit={savePolicy}
            >
              <label className="text-muted-foreground text-xs">
                模型名称
                <select
                  className="text-foreground mt-1 h-8 w-full border bg-transparent px-2 text-sm"
                  required
                  value={policy.model_name}
                  onChange={(event) =>
                    setPolicy((current) => ({
                      ...current,
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
              <label className="text-muted-foreground text-xs">
                输入价格（分/百万 Token）
                <input
                  className="text-foreground mt-1 h-8 w-full border bg-transparent px-2 text-sm"
                  required
                  type="number"
                  min="0"
                  value={policy.input_fen_per_million}
                  onChange={(event) =>
                    setPolicy((current) => ({
                      ...current,
                      input_fen_per_million: event.target.value,
                    }))
                  }
                />
              </label>
              <label className="text-muted-foreground text-xs">
                输出价格（分/百万 Token）
                <input
                  className="text-foreground mt-1 h-8 w-full border bg-transparent px-2 text-sm"
                  required
                  type="number"
                  min="0"
                  value={policy.output_fen_per_million}
                  onChange={(event) =>
                    setPolicy((current) => ({
                      ...current,
                      output_fen_per_million: event.target.value,
                    }))
                  }
                />
              </label>
              <label className="text-muted-foreground text-xs">
                缓存价格（分/百万 Token）
                <input
                  className="text-foreground mt-1 h-8 w-full border bg-transparent px-2 text-sm"
                  type="number"
                  min="0"
                  value={policy.cache_read_fen_per_million}
                  onChange={(event) =>
                    setPolicy((current) => ({
                      ...current,
                      cache_read_fen_per_million: event.target.value,
                    }))
                  }
                />
              </label>
              <label className="text-muted-foreground text-xs">
                积分倍率（10000=1:1）
                <input
                  className="text-foreground mt-1 h-8 w-full border bg-transparent px-2 text-sm"
                  required
                  type="number"
                  min="1"
                  value={policy.credit_multiplier_bps}
                  onChange={(event) =>
                    setPolicy((current) => ({
                      ...current,
                      credit_multiplier_bps: event.target.value,
                    }))
                  }
                />
              </label>
              <label className="text-muted-foreground text-xs">
                任务预占积分
                <input
                  className="text-foreground mt-1 h-8 w-full border bg-transparent px-2 text-sm"
                  required
                  type="number"
                  min="1"
                  value={policy.max_reservation_credits}
                  onChange={(event) =>
                    setPolicy((current) => ({
                      ...current,
                      max_reservation_credits: event.target.value,
                    }))
                  }
                />
              </label>
              <div className="flex items-end">
                <Button type="submit" size="sm" disabled={!policy.model_name}>
                  保存策略
                </Button>
              </div>
            </form>
            <div className="divide-y text-sm">
              {policies.map((item) => (
                <div className="flex justify-between py-2" key={item.id}>
                  <span>
                    {item.model_name}{" "}
                    {!item.active && (
                      <span className="text-muted-foreground">
                        （历史版本）
                      </span>
                    )}
                  </span>
                  <span className="text-muted-foreground">
                    输入 {item.input_fen_per_million} 分 / 输出{" "}
                    {item.output_fen_per_million} 分 · 倍率{" "}
                    {item.credit_multiplier_bps} · 预占{" "}
                    {item.max_reservation_credits} 积分
                  </span>
                </div>
              ))}
            </div>
          </div>
          <div>
            <h2 className="text-lg font-semibold">用量账单</h2>
            <p className="text-muted-foreground mb-3 text-sm">
              最近的模型调用与实际扣减积分。
            </p>
            <div className="divide-y border-y text-sm">
              {usage.length === 0 ? (
                <p className="text-muted-foreground py-3">暂无已结算用量。</p>
              ) : (
                usage.map((item) => (
                  <div
                    className="flex items-center justify-between gap-4 py-3"
                    key={`${item.run_id}-${item.model_name}`}
                  >
                    <div>
                      <p className="font-medium">
                        {item.email} · {item.model_name}
                      </p>
                      <p className="text-muted-foreground text-xs">
                        输入 {item.input_tokens} / 输出 {item.output_tokens}{" "}
                        Token
                      </p>
                    </div>
                    <p className="tabular-nums">-{item.charged_credits} 积分</p>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}
