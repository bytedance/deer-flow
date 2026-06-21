"use client";

import { useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  AlertCircleIcon,
  EyeIcon,
  ListTodoIcon,
  Loader2Icon,
  RefreshCwIcon,
} from "@/components/ui/icons";
import {
  listDefectWorkflowTodos,
  normalizeDefectWorkflowHistory,
  type DefectSummary,
  type DefectWorkflowDetail,
  type DefectWorkflowFormField,
  type DefectWorkflowHistoryEntry,
  type DefectWorkflowTodoRow,
  type WorkflowTaskFormContext,
} from "@/core/defect-workflow";
import { useBlockStore } from "@/core/genui/store";

import { DefectWorkflowTaskDetailPanel } from "./DefectWorkflowTaskDetailBlock";

interface DefectWorkflowTodoListBlockProps {
  block: {
    block_id: string;
    thread_id?: string;
    props: {
      title?: string;
      page_size?: number;
      selected_task_id?: string | number | null;
    };
  };
}

export const DEFECT_WORKFLOW_SELECTED_CONTEXT_EVENT =
  "defect-workflow:selected-context-changed";
export const DEFECT_WORKFLOW_SELECTED_TASK_STORAGE_PREFIX =
  "defect-workflow-closure:selected-task:";

type SelectedDefectWorkflowContext = Record<string, unknown>;

function selectedTaskStorageKey(threadId: string | undefined): string | null {
  return threadId ? `${DEFECT_WORKFLOW_SELECTED_TASK_STORAGE_PREFIX}${threadId}` : null;
}

function readStoredSelectedTaskId(threadId: string | undefined): string | null {
  if (typeof window === "undefined") return null;
  const key = selectedTaskStorageKey(threadId);
  return key ? window.sessionStorage.getItem(key) : null;
}

function writeStoredSelectedTaskId(threadId: string | undefined, taskId: string | number | null): void {
  if (typeof window === "undefined") return;
  const key = selectedTaskStorageKey(threadId);
  if (!key) return;
  if (taskId == null) {
    window.sessionStorage.removeItem(key);
    return;
  }
  window.sessionStorage.setItem(key, String(taskId));
}

function textValue(value: unknown, fallback = "-"): string {
  if (value === undefined || value === null || value === "") return fallback;
  return String(value);
}

function getDefectId(row: DefectWorkflowTodoRow): string | number | undefined {
  return row.defect?.id ?? row.defect?.defectId;
}

function equipmentId(defect: DefectSummary | undefined): string {
  const equipment = defect?.equipment;
  return textValue(
    equipment?.deviceId ??
      equipment?.equipmentId ??
      equipment?.id ??
      defect?.deviceId ??
      defect?.equipmentId ??
      defect?.equipmentCode,
    "",
  );
}

function defectTitle(defect: DefectSummary | undefined): string {
  return textValue(defect?.title ?? defect?.name ?? defect?.defectNo ?? defect?.defectCode ?? defect?.code, "未命名缺陷");
}

function equipmentLabel(defect: DefectSummary | undefined): string {
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

function buildSelectedContext(
  row: DefectWorkflowTodoRow,
  detail?: DefectWorkflowDetail | null,
  formContext?: WorkflowTaskFormContext | null,
  formFields?: DefectWorkflowFormField[],
  workflowHistory?: DefectWorkflowHistoryEntry[],
): SelectedDefectWorkflowContext {
  const defect = detail?.defect ?? row.defect;
  const task = detail?.currentTask ?? row;
  return {
    selected: true,
    taskId: row.taskId,
    nodeName: row.nodeName ?? task?.nodeName,
    nodeKey: row.nodeKey ?? task?.nodeKey,
    defectId: getDefectId(row) ?? defect?.id ?? defect?.defectId,
    defectNo: defect?.defectNo ?? defect?.defectCode ?? defect?.code,
    defectTitle: defectTitle(defect),
    defectStatus: defect?.status ?? task?.["status"],
    equipmentId: equipmentId(defect),
    equipmentName: equipmentLabel(defect),
    equipmentCode: defect?.equipmentCode ?? defect?.equipment?.code,
    deviceId: defect?.deviceId ?? defect?.equipment?.deviceId,
    allowedActions:
      task?.allowedActions ??
      formContext?.businessMetadata?.allowedActions ??
      formContext?.allowedActions,
    formFields: formFields?.map((field) => ({
      name: field.name,
      label: field.label,
      required: field.required,
      type: field.type,
    })),
    workflowHistory: (workflowHistory ?? normalizeDefectWorkflowHistory(detail)).map((entry) => ({
      taskId: entry.taskId,
      nodeName: entry.nodeName,
      action: entry.action,
      actionLabel: entry.actionLabel,
      operatorName: entry.operatorName,
      occurredAt: entry.occurredAt,
      summary: entry.summary,
      formData: entry.formData,
    })),
  };
}

function emitSelectedContext(
  threadId: string | undefined,
  context: SelectedDefectWorkflowContext | null,
) {
  if (typeof window === "undefined" || !threadId) return;
  window.dispatchEvent(
    new CustomEvent(DEFECT_WORKFLOW_SELECTED_CONTEXT_EVENT, {
      detail: {
        threadId,
        context,
      },
    }),
  );
}

function claimStatus(row: DefectWorkflowTodoRow): string {
  if (row.claimedByCurrentUser || row.assignedToCurrentUser) return "已认领";
  if (row.claimable || row.candidateForCurrentUser || row.claimRequired) return "待认领";
  return "只读";
}

function claimStatusClass(row: DefectWorkflowTodoRow): string {
  if (row.claimedByCurrentUser || row.assignedToCurrentUser) {
    return "border-emerald-200 bg-emerald-50 text-emerald-700";
  }
  if (row.claimable || row.candidateForCurrentUser || row.claimRequired) {
    return "border-amber-200 bg-amber-50 text-amber-700";
  }
  return "border-border bg-muted text-muted-foreground";
}

export default function DefectWorkflowTodoListBlock({ block }: DefectWorkflowTodoListBlockProps) {
  const { title = "缺陷待办", page_size = 20, selected_task_id } = block.props;
  const updateBlockProps = useBlockStore((state) => state.updateBlockProps);
  const [rows, setRows] = useState<DefectWorkflowTodoRow[]>([]);
  const [total, setTotal] = useState<number | undefined>();
  const [selectedTaskId, setSelectedTaskId] = useState<string | number | null>(
    selected_task_id ?? readStoredSelectedTaskId(block.thread_id),
  );
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  const selectedRow = useMemo(
    () => rows.find((row) => String(row.taskId) === String(selectedTaskId)) ?? null,
    [rows, selectedTaskId],
  );

  useEffect(() => {
    if (selected_task_id == null) return;
    if (String(selected_task_id) === String(selectedTaskId)) return;
    setSelectedTaskId(selected_task_id);
  }, [selected_task_id, selectedTaskId]);

  useEffect(() => {
    emitSelectedContext(
      block.thread_id,
      selectedRow ? buildSelectedContext(selectedRow) : null,
    );
  }, [block.thread_id, selectedRow]);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    listDefectWorkflowTodos({ pageNo: 1, pageSize: page_size })
      .then((page) => {
        if (controller.signal.aborted) return;
        setRows(page.rows ?? []);
        setTotal(page.total);
        if (selectedTaskId && !(page.rows ?? []).some((row) => String(row.taskId) === String(selectedTaskId))) {
          setSelectedTaskId(null);
          updateBlockProps(block.block_id, { selected_task_id: null });
          writeStoredSelectedTaskId(block.thread_id, null);
        }
      })
      .catch((err) => {
        if (controller.signal.aborted) return;
        setError(err instanceof Error ? err.message : "加载缺陷待办失败");
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [page_size, reloadKey, selectedTaskId]);

  const refresh = () => setReloadKey((key) => key + 1);
  const selectTask = (taskId: string | number) => {
    setSelectedTaskId(taskId);
    updateBlockProps(block.block_id, { selected_task_id: taskId });
    writeStoredSelectedTaskId(block.thread_id, taskId);
  };

  return (
    <div className="rounded-lg border bg-card" role="region" aria-label={title}>
      <div className="flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3">
        <div className="flex items-center gap-2">
          <ListTodoIcon />
          <div>
            <h3 className="text-sm font-semibold">{title}</h3>
            <p className="text-xs text-muted-foreground">
              {total === undefined ? `${rows.length} 条` : `共 ${total} 条`}，点击详情处理当前节点
            </p>
          </div>
        </div>
        <Button variant="outline" size="sm" onClick={refresh} disabled={loading}>
          <RefreshCwIcon className={loading ? "animate-spin" : ""} />
          刷新
        </Button>
      </div>

      {error && (
        <div className="flex items-center gap-2 border-b px-4 py-3 text-sm text-destructive">
          <AlertCircleIcon />
          {error}
        </div>
      )}

      <div className="overflow-x-auto">
        <table className="w-full min-w-[760px] text-sm">
          <thead>
            <tr className="border-b bg-muted/40 text-left text-xs font-medium text-muted-foreground">
              <th className="px-4 py-2">缺陷</th>
              <th className="px-4 py-2">设备</th>
              <th className="px-4 py-2">当前节点</th>
              <th className="px-4 py-2">状态</th>
              <th className="px-4 py-2">操作</th>
            </tr>
          </thead>
          <tbody>
            {loading && rows.length === 0 ? (
              <tr>
                <td className="px-4 py-6 text-muted-foreground" colSpan={5}>
                  <span className="inline-flex items-center gap-2">
                    <Loader2Icon className="animate-spin" />
                    正在加载缺陷待办...
                  </span>
                </td>
              </tr>
            ) : rows.length === 0 ? (
              <tr>
                <td className="px-4 py-6 text-muted-foreground" colSpan={5}>
                  当前没有缺陷待办。
                </td>
              </tr>
            ) : (
              rows.map((row) => {
                const isSelected = String(row.taskId) === String(selectedTaskId);
                return (
                  <tr
                    key={String(row.taskId)}
                    className={`border-b last:border-0 ${isSelected ? "bg-primary/5" : "hover:bg-muted/30"}`}
                  >
                    <td className="px-4 py-3">
                      <div className="font-medium">{defectTitle(row.defect)}</div>
                      <div className="mt-1 text-xs text-muted-foreground">
                        {textValue(row.defect?.defectNo ?? row.defect?.defectCode ?? row.defect?.code ?? getDefectId(row))}
                      </div>
                    </td>
                    <td className="px-4 py-3">{equipmentLabel(row.defect)}</td>
                    <td className="px-4 py-3">
                      <div>{textValue(row.nodeName)}</div>
                      <div className="mt-1 text-xs text-muted-foreground">任务 {textValue(row.taskId)}</div>
                    </td>
                    <td className="px-4 py-3">
                      <span className={`rounded border px-2 py-0.5 text-xs ${claimStatusClass(row)}`}>
                        {claimStatus(row)}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <Button
                        variant={isSelected ? "secondary" : "outline"}
                        size="sm"
                        onClick={() => selectTask(row.taskId)}
                        disabled={!getDefectId(row)}
                      >
                        <EyeIcon />
                        详情
                      </Button>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      <div className="border-t p-4">
        <DefectWorkflowTaskDetailPanel
          defectId={selectedRow ? getDefectId(selectedRow) : undefined}
          taskId={selectedRow?.taskId}
          initialTodo={selectedRow}
          onChanged={refresh}
          onContextChanged={(detail, formContext, formFields, workflowHistory) => {
            if (!selectedRow) return;
            emitSelectedContext(
              block.thread_id,
              buildSelectedContext(selectedRow, detail, formContext, formFields, workflowHistory),
            );
          }}
        />
      </div>
    </div>
  );
}
