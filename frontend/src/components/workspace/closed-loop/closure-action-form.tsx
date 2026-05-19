"use client";

import { useMemo, useState } from "react";

import { useAuth } from "@/core/auth/AuthProvider";
import type {
  ClosureAction,
  ClosureStatus,
  ClosureTicket,
} from "@/core/closed-loop";

interface ActionDef {
  action: ClosureAction;
  label: string;
  tone: "primary" | "danger" | "neutral";
  requiresVerify?: boolean;
}

const ACTIONS_BY_STATUS: Record<ClosureStatus, ActionDef[]> = {
  pending: [{ action: "assign", label: "派单", tone: "primary" }],
  assigned: [{ action: "start", label: "开始处置", tone: "primary" }],
  in_progress: [
    { action: "submit_verification", label: "提交验证", tone: "primary" },
  ],
  pending_verification: [
    {
      action: "verify_close",
      label: "验证关闭",
      tone: "primary",
      requiresVerify: true,
    },
    { action: "reject", label: "退回", tone: "danger", requiresVerify: true },
  ],
  closed: [],
  rejected: [],
};

function canVerify(systemRole: string | undefined): boolean {
  return systemRole === "superadmin" || systemRole === "tenant_admin";
}

export interface ClosureActionFormProps {
  ticket: ClosureTicket;
  pending: boolean;
  onSubmit: (
    action: ClosureAction,
    payload?: Record<string, unknown>,
  ) => void | Promise<void>;
}

export function ClosureActionForm({
  ticket,
  pending,
  onSubmit,
}: ClosureActionFormProps) {
  const { user } = useAuth();
  const allowed = useMemo<ActionDef[]>(() => {
    const base = ACTIONS_BY_STATUS[ticket.status] ?? [];
    if (canVerify(user?.system_role)) return base;
    return base.filter((a) => !a.requiresVerify);
  }, [ticket.status, user?.system_role]);

  const [activeAction, setActiveAction] = useState<ClosureAction | null>(null);
  const [assignee, setAssignee] = useState("");
  const [summary, setSummary] = useState("");
  const [reason, setReason] = useState("");

  if (allowed.length === 0) {
    return (
      <p className="text-muted-foreground text-xs">
        当前状态下无可执行动作。
      </p>
    );
  }

  const reset = () => {
    setActiveAction(null);
    setAssignee("");
    setSummary("");
    setReason("");
  };

  const handleSubmit = async (action: ClosureAction) => {
    let payload: Record<string, unknown> | undefined;
    if (action === "assign") {
      const trimmed = assignee.trim();
      if (!trimmed) return;
      payload = { assignee_id: trimmed };
    } else if (action === "submit_verification") {
      const trimmed = summary.trim();
      if (!trimmed) return;
      payload = { verification_summary: trimmed };
    } else if (action === "verify_close") {
      const trimmed = summary.trim();
      payload = trimmed ? { verification_summary: trimmed } : undefined;
    } else if (action === "reject") {
      const trimmed = reason.trim();
      if (!trimmed) return;
      payload = { rejection_reason: trimmed };
    }
    await onSubmit(action, payload);
    reset();
  };

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-2">
        {allowed.map((a) => {
          const cls =
            a.tone === "primary"
              ? "bg-primary text-primary-foreground hover:opacity-90"
              : a.tone === "danger"
                ? "bg-destructive text-destructive-foreground hover:opacity-90"
                : "bg-muted text-foreground hover:bg-accent";
          if (a.action === "start") {
            // start has no payload; submit immediately
            return (
              <button
                key={a.action}
                type="button"
                disabled={pending}
                className={`rounded px-3 py-1 text-xs disabled:opacity-50 ${cls}`}
                onClick={() => void handleSubmit(a.action)}
              >
                {a.label}
              </button>
            );
          }
          const isActive = activeAction === a.action;
          return (
            <button
              key={a.action}
              type="button"
              disabled={pending}
              className={`rounded px-3 py-1 text-xs disabled:opacity-50 ${cls} ${
                isActive ? "ring-2 ring-offset-1 ring-foreground/30" : ""
              }`}
              onClick={() => setActiveAction(isActive ? null : a.action)}
            >
              {a.label}
            </button>
          );
        })}
      </div>

      {activeAction === "assign" && (
        <Inline
          label="受理人 ID"
          value={assignee}
          placeholder="输入受理人 user id"
          required
          onChange={setAssignee}
          onSubmit={() => void handleSubmit("assign")}
          onCancel={reset}
          submitLabel="派单"
          pending={pending}
        />
      )}
      {activeAction === "submit_verification" && (
        <Inline
          label="验证摘要"
          value={summary}
          placeholder="处置经过、验证依据"
          required
          multiline
          onChange={setSummary}
          onSubmit={() => void handleSubmit("submit_verification")}
          onCancel={reset}
          submitLabel="提交验证"
          pending={pending}
        />
      )}
      {activeAction === "verify_close" && (
        <Inline
          label="验证摘要（可选）"
          value={summary}
          placeholder="确认整改有效的依据"
          multiline
          onChange={setSummary}
          onSubmit={() => void handleSubmit("verify_close")}
          onCancel={reset}
          submitLabel="验证关闭"
          pending={pending}
        />
      )}
      {activeAction === "reject" && (
        <Inline
          label="退回原因"
          value={reason}
          placeholder="说明为何无法关闭，请退回处置人"
          required
          multiline
          onChange={setReason}
          onSubmit={() => void handleSubmit("reject")}
          onCancel={reset}
          submitLabel="退回"
          pending={pending}
        />
      )}
    </div>
  );
}

function Inline({
  label,
  value,
  placeholder,
  required,
  multiline,
  pending,
  submitLabel,
  onChange,
  onSubmit,
  onCancel,
}: {
  label: string;
  value: string;
  placeholder?: string;
  required?: boolean;
  multiline?: boolean;
  pending: boolean;
  submitLabel: string;
  onChange: (v: string) => void;
  onSubmit: () => void;
  onCancel: () => void;
}) {
  const disabled = pending || (required && value.trim().length === 0);
  return (
    <div className="bg-muted/30 rounded border p-2">
      <label className="text-muted-foreground mb-1 block text-[11px]">
        {label}
      </label>
      {multiline ? (
        <textarea
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          rows={3}
          className="bg-background w-full rounded border px-2 py-1 text-xs"
        />
      ) : (
        <input
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          className="bg-background w-full rounded border px-2 py-1 text-xs"
        />
      )}
      <div className="mt-2 flex justify-end gap-2">
        <button
          type="button"
          className="hover:bg-accent rounded border px-2 py-1 text-xs"
          onClick={onCancel}
          disabled={pending}
        >
          取消
        </button>
        <button
          type="button"
          className="bg-primary text-primary-foreground rounded px-3 py-1 text-xs disabled:opacity-50"
          onClick={onSubmit}
          disabled={disabled}
        >
          {submitLabel}
        </button>
      </div>
    </div>
  );
}
