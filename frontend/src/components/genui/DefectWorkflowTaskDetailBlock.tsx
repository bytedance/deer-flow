"use client";

import { useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  AlertCircleIcon,
  CheckCircle2Icon,
  Loader2Icon,
  PlayIcon,
  RefreshCwIcon,
  SendIcon,
} from "@/components/ui/icons";
import {
  claimDefectWorkflowTask,
  convertVFormContextToFormModel,
  getDefectWorkflowDetail,
  getDefectWorkflowFormContext,
  normalizeDefectWorkflowHistory,
  submitDefectWorkflowTask,
  type DefectSummary,
  type DefectWorkflowDetail,
  type DefectWorkflowFormField,
  type DefectWorkflowHistoryEntry,
  type DefectWorkflowFormModel,
  type DefectWorkflowTask,
  type DefectWorkflowTodoRow,
  type WorkflowTaskFormContext,
} from "@/core/defect-workflow";

interface DefectWorkflowTaskDetailBlockProps {
  block: {
    props: {
      defect_id?: string | number;
      task_id?: string | number;
      title?: string;
    };
  };
}

interface DetailPanelProps {
  defectId?: string | number;
  taskId?: string | number;
  title?: string;
  initialTodo?: DefectWorkflowTodoRow | null;
  onChanged?: () => void;
  onContextChanged?: (
    detail: DefectWorkflowDetail | null,
    formContext: WorkflowTaskFormContext | null,
    formFields: DefectWorkflowFormField[],
    workflowHistory: DefectWorkflowHistoryEntry[],
  ) => void;
}

type LoadStatus = "idle" | "loading" | "ready" | "error";

const ACTION_LABELS: Record<string, string> = {
  SUBMIT: "通过",
  APPROVE: "通过",
  PASS: "通过",
  REJECT: "驳回",
  CANCEL: "取消",
};

function textValue(value: unknown, fallback = "-"): string {
  if (value === undefined || value === null || value === "") return fallback;
  return String(value);
}

function actionLabel(action: string): string {
  return ACTION_LABELS[action.toUpperCase()] ?? action;
}

function formatTime(value: string | undefined): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", { hour12: false });
}

function defectTitle(defect?: DefectSummary | null): string {
  return textValue(defect?.title ?? defect?.name ?? defect?.defectNo ?? defect?.defectCode ?? defect?.code, "缺陷详情");
}

function equipmentLabel(defect?: DefectSummary | null): string {
  const equipment = defect?.equipment;
  return textValue(
      equipment?.deviceName ??
      equipment?.equipmentName ??
      equipment?.name ??
      defect?.equipmentName ??
      defect?.equipmentCode ??
      defect?.deviceId ??
      defect?.equipmentId,
  );
}

function historyTaskIds(detail: DefectWorkflowDetail | null): string[] {
  const submissions = Array.isArray(detail?.submissions) ? detail.submissions : [];
  const ids = new Set<string>();
  for (const submission of submissions) {
    if (typeof submission !== "object" || submission === null || Array.isArray(submission)) continue;
    const taskId = (submission as Record<string, unknown>).taskId;
    if (taskId !== undefined && taskId !== null && taskId !== "") {
      ids.add(String(taskId));
    }
  }
  return Array.from(ids);
}

function isEmptyRequiredValue(field: DefectWorkflowFormField, value: unknown): boolean {
  if (!field.required) return false;
  if (field.type === "checkbox") return value !== true;
  if (field.type === "multi-select") return !Array.isArray(value) || value.length === 0;
  return value === undefined || value === null || value === "";
}

function shouldValidateForm(action: string): boolean {
  const normalized = action.toUpperCase();
  return normalized !== "REJECT" && normalized !== "CANCEL";
}

function normalizeSubmitData(
  model: DefectWorkflowFormModel,
  values: Record<string, unknown>,
): Record<string, unknown> {
  const result: Record<string, unknown> = {};
  for (const field of model.fields) {
    const value = values[field.name];
    if ((field.type === "select" || field.type === "radio") && field.options) {
      result[field.name] = field.options.find((option) => option.value === String(value))?.rawValue ?? value;
    } else if (field.type === "multi-select" && field.options && Array.isArray(value)) {
      result[field.name] = value.map((item) =>
        field.options?.find((option) => option.value === String(item))?.rawValue ?? item,
      );
    } else {
      result[field.name] = value;
    }
  }
  return result;
}

function statusBadge(task?: DefectWorkflowTask | null) {
  if (!task) return null;
  if (task.claimedByCurrentUser || task.assignedToCurrentUser) {
    return <span className="rounded border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-xs text-emerald-700">已认领</span>;
  }
  if (task.claimable || task.candidateForCurrentUser) {
    return <span className="rounded border border-amber-200 bg-amber-50 px-2 py-0.5 text-xs text-amber-700">待认领</span>;
  }
  return <span className="rounded border px-2 py-0.5 text-xs text-muted-foreground">只读</span>;
}

function HistoryEntryCard({ entry }: { entry: DefectWorkflowHistoryEntry }) {
  return (
    <div className="rounded-md border bg-background p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium">{entry.nodeName}</span>
            <span className="rounded border bg-muted px-2 py-0.5 text-xs">
              {entry.actionLabel}
            </span>
          </div>
          <div className="mt-1 text-xs text-muted-foreground">
            {textValue(entry.operatorName, "未知处理人")} · {formatTime(entry.occurredAt)}
            {entry.taskId ? ` · 任务 ${entry.taskId}` : ""}
          </div>
        </div>
      </div>
      {entry.summary && (
        <div className="mt-3 rounded border bg-muted/20 px-3 py-2 text-sm">
          {entry.summary}
        </div>
      )}
      {entry.formData.length > 0 && (
        <details className="mt-3 rounded border bg-muted/10">
          <summary className="cursor-pointer px-3 py-2 text-xs font-medium text-muted-foreground">
            查看表单数据（{entry.formData.length} 项）
          </summary>
          <div className="grid gap-2 border-t p-3 text-sm sm:grid-cols-2">
            {entry.formData.map((item) => (
              <div key={item.name} className="min-w-0">
                <div className="text-xs text-muted-foreground">{item.label}</div>
                <div className="mt-0.5 break-words font-medium">{item.value}</div>
              </div>
            ))}
          </div>
        </details>
      )}
    </div>
  );
}

function WorkflowHistoryPanel({ entries }: { entries: DefectWorkflowHistoryEntry[] }) {
  return (
    <section className="grid gap-2">
      <div>
        <h4 className="text-sm font-semibold">历史处理记录</h4>
        <p className="mt-1 text-xs text-muted-foreground">
          已完成节点 {entries.length} 条，可用于参考当前节点处理。
        </p>
      </div>
      {entries.length === 0 ? (
        <div className="rounded-md border border-dashed p-4 text-sm text-muted-foreground">
          暂无历史已处理节点。
        </div>
      ) : (
        <div className="grid gap-2">
          {entries.map((entry) => (
            <HistoryEntryCard key={entry.id} entry={entry} />
          ))}
        </div>
      )}
    </section>
  );
}

function FormFieldControl({
  field,
  value,
  disabled,
  onChange,
}: {
  field: DefectWorkflowFormField;
  value: unknown;
  disabled: boolean;
  onChange: (value: unknown) => void;
}) {
  const baseClass = "w-full rounded-md border bg-background px-3 py-2 text-sm";
  if (field.type === "textarea") {
    return (
      <textarea
        className={`${baseClass} min-h-24`}
        value={textValue(value, "")}
        placeholder={field.placeholder}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
      />
    );
  }
  if (field.type === "select") {
    return (
      <select
        className={baseClass}
        value={textValue(value, "")}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
      >
        <option value="">{field.placeholder ?? "请选择"}</option>
        {field.options?.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    );
  }
  if (field.type === "radio") {
    return (
      <div className="flex flex-wrap gap-3">
        {field.options?.map((option) => (
          <label key={option.value} className="flex items-center gap-2 text-sm">
            <input
              type="radio"
              checked={String(value ?? "") === option.value}
              disabled={disabled}
              onChange={() => onChange(option.value)}
            />
            {option.label}
          </label>
        ))}
      </div>
    );
  }
  if (field.type === "multi-select") {
    const selected = new Set(Array.isArray(value) ? value.map(String) : []);
    return (
      <div className="grid gap-2 rounded-md border p-3 sm:grid-cols-2">
        {field.options?.map((option) => (
          <label key={option.value} className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={selected.has(option.value)}
              disabled={disabled}
              onChange={(event) => {
                const next = new Set(selected);
                if (event.target.checked) next.add(option.value);
                else next.delete(option.value);
                onChange(Array.from(next));
              }}
            />
            {option.label}
          </label>
        ))}
      </div>
    );
  }
  if (field.type === "checkbox") {
    return (
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={Boolean(value)}
          disabled={disabled}
          onChange={(event) => onChange(event.target.checked)}
        />
        <span>{field.placeholder ?? "是"}</span>
      </label>
    );
  }
  return (
    <input
      className={baseClass}
      type={field.type}
      value={textValue(value, "")}
      placeholder={field.placeholder}
      disabled={disabled}
      onChange={(event) => {
        if (field.type === "number") {
          onChange(event.target.value === "" ? "" : Number(event.target.value));
        } else {
          onChange(event.target.value);
        }
      }}
    />
  );
}

export function DefectWorkflowTaskDetailPanel({
  defectId,
  taskId,
  title,
  initialTodo,
  onChanged,
  onContextChanged,
}: DetailPanelProps) {
  const [status, setStatus] = useState<LoadStatus>("idle");
  const [detail, setDetail] = useState<DefectWorkflowDetail | null>(null);
  const [formContext, setFormContext] = useState<WorkflowTaskFormContext | null>(null);
  const [historyContextsByTaskId, setHistoryContextsByTaskId] = useState<Record<string, WorkflowTaskFormContext | null>>({});
  const [formData, setFormData] = useState<Record<string, unknown>>({});
  const [comment, setComment] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  const formModel = useMemo(
    () => convertVFormContextToFormModel(formContext),
    [formContext],
  );
  const workflowHistory = useMemo(
    () => normalizeDefectWorkflowHistory(detail, { contextsByTaskId: historyContextsByTaskId }),
    [detail, historyContextsByTaskId],
  );

  const currentTask = detail?.currentTask ?? initialTodo ?? null;
  const defect = detail?.defect ?? initialTodo?.defect ?? null;
  const allowedActions = currentTask?.allowedActions ?? formContext?.allowedActions ?? formContext?.businessMetadata?.allowedActions ?? [];
  const canClaim = Boolean(currentTask?.claimable || (currentTask?.claimRequired && !currentTask?.claimedByCurrentUser));
  const shouldShowCurrentTaskForm = !canClaim;
  const actionsDisabled =
    Boolean(currentTask?.claimRequired && !currentTask?.claimedByCurrentUser && !currentTask?.assignedToCurrentUser) ||
    formModel.hasBlockingUnsupportedRequired;

  useEffect(() => {
    if (!defectId || !taskId) return;
    onContextChanged?.(detail, formContext, formModel.fields, workflowHistory);
  }, [defectId, taskId, detail, formContext, formModel.fields, workflowHistory, onContextChanged]);

  const loadDetail = useMemo(
    () => async (signal: AbortSignal) => {
      if (!defectId || !taskId) {
        setStatus("idle");
        return;
      }
      setStatus("loading");
      setError(null);
      try {
        const [nextDetail, nextContext] = await Promise.all([
          getDefectWorkflowDetail(defectId),
          getDefectWorkflowFormContext(taskId),
        ]);
        if (signal.aborted) return;
        const historyContextEntries = await Promise.all(
          historyTaskIds(nextDetail).map(async (historyTaskId) => {
            if (String(historyTaskId) === String(taskId)) {
              return [historyTaskId, nextContext] as const;
            }
            try {
              const context = await getDefectWorkflowFormContext(historyTaskId);
              return [historyTaskId, context] as const;
            } catch {
              return [historyTaskId, null] as const;
            }
          }),
        );
        if (signal.aborted) return;
        const nextModel = convertVFormContextToFormModel(nextContext);
        setDetail(nextDetail);
        setFormContext(nextContext);
        setHistoryContextsByTaskId(Object.fromEntries(historyContextEntries));
        setFormData(nextModel.defaultValues);
        setStatus("ready");
      } catch (err) {
        if (signal.aborted) return;
        setError(err instanceof Error ? err.message : "加载详情失败");
        setStatus("error");
      }
    },
    [defectId, taskId],
  );

  useEffect(() => {
    const controller = new AbortController();
    void loadDetail(controller.signal);
    return () => controller.abort();
  }, [loadDetail, reloadKey]);

  const refresh = () => {
    setSuccess(null);
    setReloadKey((key) => key + 1);
    onChanged?.();
  };

  const handleClaim = async () => {
    if (!defectId || !taskId) return;
    setBusyAction("claim");
    setError(null);
    try {
      await claimDefectWorkflowTask(defectId, taskId, comment || undefined);
      setSuccess("已认领当前节点");
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "认领失败");
    } finally {
      setBusyAction(null);
    }
  };

  const handleSubmit = async (action: string) => {
    if (!defectId || !taskId) return;
    setError(null);
    setSuccess(null);
    if (shouldValidateForm(action)) {
      const missing = formModel.fields.find((field) =>
        isEmptyRequiredValue(field, formData[field.name]),
      );
      if (missing) {
        setError(`请先填写必填字段：${missing.label}`);
        return;
      }
    }
    if (formModel.hasBlockingUnsupportedRequired) {
      setError("当前节点包含暂不支持的必填控件，请在闭环平台处理。");
      return;
    }

    setBusyAction(action);
    try {
      await submitDefectWorkflowTask(defectId, taskId, {
        action,
        formData: normalizeSubmitData(formModel, formData),
        comment: comment || undefined,
      });
      setSuccess(`已提交：${actionLabel(action)}`);
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "提交失败");
    } finally {
      setBusyAction(null);
    }
  };

  if (!defectId || !taskId) {
    return (
      <div className="rounded-md border border-dashed p-4 text-sm text-muted-foreground">
        请选择一条缺陷待办查看详情。
      </div>
    );
  }

  return (
    <div className="rounded-lg border bg-card" role="region" aria-label={title ?? "缺陷流程详情"}>
      <div className="flex flex-wrap items-start justify-between gap-3 border-b px-4 py-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="truncate text-sm font-semibold">{title ?? defectTitle(defect)}</h3>
            {statusBadge(currentTask)}
          </div>
          <p className="mt-1 text-xs text-muted-foreground">
            节点：{textValue(currentTask?.nodeName)} · 任务：{textValue(taskId)}
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={refresh} disabled={status === "loading"}>
          <RefreshCwIcon className={status === "loading" ? "animate-spin" : ""} />
          刷新
        </Button>
      </div>

      {status === "loading" && (
        <div className="flex items-center gap-2 px-4 py-6 text-sm text-muted-foreground">
          <Loader2Icon className="animate-spin" />
          正在加载流程详情...
        </div>
      )}

      {status === "error" && (
        <div className="flex items-center gap-2 px-4 py-4 text-sm text-destructive">
          <AlertCircleIcon />
          {error}
        </div>
      )}

      {status === "ready" && (
        <div className="grid gap-4 p-4">
          <div className="grid gap-3 text-sm md:grid-cols-3">
            <div>
              <div className="text-xs text-muted-foreground">缺陷</div>
              <div className="mt-1 font-medium">{defectTitle(defect)}</div>
            </div>
            <div>
              <div className="text-xs text-muted-foreground">设备</div>
              <div className="mt-1 font-medium">{equipmentLabel(defect)}</div>
            </div>
            <div>
              <div className="text-xs text-muted-foreground">状态</div>
              <div className="mt-1 font-medium">{textValue(defect?.status)}</div>
            </div>
          </div>

          {detail?.processView !== undefined && (
            <div className="rounded-md border bg-muted/20 p-3 text-xs text-muted-foreground">
              流程视图已由闭环平台返回，可按当前节点信息继续处理。
            </div>
          )}

          <WorkflowHistoryPanel entries={workflowHistory} />

          {shouldShowCurrentTaskForm ? (
            <>
              {formModel.unsupportedWidgets.length > 0 && (
                <div className="rounded-md border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800">
                  暂不支持的表单控件：
                  {formModel.unsupportedWidgets.map((widget) => widget.label ?? widget.name ?? widget.type).join("、")}
                  {formModel.hasBlockingUnsupportedRequired ? "。其中包含必填项，请在闭环平台处理。" : ""}
                </div>
              )}

              <div className="grid gap-3">
                {formModel.fields.length === 0 ? (
                  <div className="rounded-md border border-dashed p-4 text-sm text-muted-foreground">
                    当前节点没有需要填写的表单字段。
                  </div>
                ) : (
                  formModel.fields.map((field) => (
                    <label key={field.name} className="grid gap-1.5">
                      <span className="text-xs font-medium">
                        {field.label}
                        {field.required && <span className="text-destructive"> *</span>}
                      </span>
                      <FormFieldControl
                        field={field}
                        value={formData[field.name]}
                        disabled={Boolean(busyAction)}
                        onChange={(value) =>
                          setFormData((current) => ({ ...current, [field.name]: value }))
                        }
                      />
                    </label>
                  ))
                )}
              </div>

              <label className="grid gap-1.5">
                <span className="text-xs font-medium">处理意见</span>
                <textarea
                  className="min-h-20 rounded-md border bg-background px-3 py-2 text-sm"
                  value={comment}
                  disabled={Boolean(busyAction)}
                  onChange={(event) => setComment(event.target.value)}
                  placeholder="可填写本次节点处理说明"
                />
              </label>
            </>
          ) : (
            <div className="rounded-md border border-dashed p-4 text-sm text-muted-foreground">
              当前节点待认领。认领后将展示当前节点表单和可操作按钮。
            </div>
          )}

          {error && (
            <div className="flex items-center gap-2 rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
              <AlertCircleIcon />
              {error}
            </div>
          )}
          {success && (
            <div className="flex items-center gap-2 rounded-md border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-700">
              <CheckCircle2Icon />
              {success}
            </div>
          )}

          <div className="flex flex-wrap gap-2 border-t pt-3">
            {canClaim && (
              <Button variant="outline" size="sm" onClick={handleClaim} disabled={Boolean(busyAction)}>
                <PlayIcon />
                {busyAction === "claim" ? "认领中..." : "认领"}
              </Button>
            )}
            {shouldShowCurrentTaskForm && allowedActions.length > 0 ? (
                allowedActions.map((action) => (
                  <Button
                    key={action}
                    variant={action.toUpperCase() === "REJECT" ? "destructive" : action.toUpperCase() === "CANCEL" ? "outline" : "default"}
                    size="sm"
                    onClick={() => void handleSubmit(action)}
                    disabled={Boolean(busyAction) || actionsDisabled}
                  >
                    <SendIcon />
                    {busyAction === action ? "提交中..." : actionLabel(action)}
                  </Button>
                ))
              ) : !canClaim ? (
              <span className="self-center text-xs text-muted-foreground">
                当前节点暂无可操作按钮。
              </span>
            ) : null}
          </div>
        </div>
      )}
    </div>
  );
}

export default function DefectWorkflowTaskDetailBlock({ block }: DefectWorkflowTaskDetailBlockProps) {
  return (
    <DefectWorkflowTaskDetailPanel
      defectId={block.props.defect_id}
      taskId={block.props.task_id}
      title={block.props.title}
    />
  );
}
