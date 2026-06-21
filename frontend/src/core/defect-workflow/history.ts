import type { DefectWorkflowDetail, WorkflowTaskFormContext } from "./types";

export interface DefectWorkflowHistoryFormValue {
  name: string;
  label: string;
  value: string;
}

export interface DefectWorkflowHistoryEntry {
  id: string;
  taskId?: string;
  nodeKey?: string;
  nodeName: string;
  action?: string;
  actionLabel: string;
  operatorName?: string;
  occurredAt?: string;
  summary?: string;
  formData: DefectWorkflowHistoryFormValue[];
}

export interface NormalizeDefectWorkflowHistoryOptions {
  contextsByTaskId?: Record<string, WorkflowTaskFormContext | null | undefined>;
}

const ACTION_LABELS: Record<string, string> = {
  SUBMIT: "通过",
  APPROVE: "通过",
  PASS: "通过",
  COMPLETE_TASK: "完成",
  REJECT: "驳回",
  CANCEL: "取消",
  CREATE: "创建",
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function recordValue(value: unknown, key: string): unknown {
  return isRecord(value) ? value[key] : undefined;
}

function stringValue(value: unknown): string | undefined {
  if (value === undefined || value === null || value === "") return undefined;
  return String(value);
}

function actionLabel(action: unknown): string {
  const text = stringValue(action);
  if (!text) return "-";
  return ACTION_LABELS[text.toUpperCase()] ?? text;
}

function parseFormData(value: unknown): Record<string, unknown> {
  if (isRecord(value)) return value;
  if (typeof value !== "string" || !value.trim()) return {};
  try {
    const parsed = JSON.parse(value) as unknown;
    return isRecord(parsed) ? parsed : {};
  } catch {
    return {};
  }
}

function parseJsonRecord(value: unknown): Record<string, unknown> {
  if (isRecord(value)) return value;
  if (typeof value !== "string" || !value.trim()) return {};
  try {
    const parsed = JSON.parse(value) as unknown;
    return isRecord(parsed) ? parsed : {};
  } catch {
    return {};
  }
}

function parseMaybeJsonRecord(value: unknown): Record<string, unknown> {
  if (isRecord(value)) return value;
  return parseJsonRecord(value);
}

function displayValue(value: unknown): string {
  if (value === true) return "是";
  if (value === false) return "否";
  if (value === undefined || value === null || value === "") return "-";
  if (Array.isArray(value)) return value.map(displayValue).join("、");
  if (isRecord(value)) return JSON.stringify(value);
  return String(value);
}

function fieldKey(field: Record<string, unknown>): string | undefined {
  const options = isRecord(field.options) ? field.options : {};
  return stringValue(
    options.name ??
      options.fieldName ??
      field.name ??
      field.key ??
      field.id,
  );
}

function fieldLabel(field: Record<string, unknown>): string | undefined {
  const options = isRecord(field.options) ? field.options : {};
  return stringValue(
    options.label ??
      options.title ??
      options.fieldName ??
      field.label ??
      field.title ??
      field.name,
  );
}

function collectFormFieldLabels(schema: unknown): Map<string, string> {
  const labels = new Map<string, string>();

  function addField(field: unknown) {
    if (!isRecord(field)) return;
    const name = fieldKey(field);
    const label = fieldLabel(field);
    if (name && label) labels.set(name, label);
  }

  function walkWidgets(widgets: unknown) {
    if (!Array.isArray(widgets)) return;
    for (const widget of widgets) {
      addField(widget);
      if (isRecord(widget)) {
        walkWidgets(widget.widgetList);
        const cols = widget.cols;
        if (Array.isArray(cols)) {
          for (const col of cols) {
            if (isRecord(col)) walkWidgets(col.widgetList);
          }
        }
      }
    }
  }

  if (!isRecord(schema)) return labels;

  walkWidgets(schema.widgetList);
  const fields = schema.fields;
  if (Array.isArray(fields)) {
    for (const field of fields) addField(field);
  }

  return labels;
}

function collectContextFieldLabels(
  context: WorkflowTaskFormContext | null | undefined,
): Map<string, string> {
  const labels = new Map<string, string>();
  const schemas: unknown[] = [
    context?.formSchema,
    parseMaybeJsonRecord(recordValue(context?.form, "formJson")),
    parseMaybeJsonRecord(recordValue(context?.form, "formContent")),
    context?.form,
    context?.widgetList ? { widgetList: context.widgetList } : undefined,
    parseMaybeJsonRecord(context?.formContent),
    parseMaybeJsonRecord(context?.formJson),
    parseMaybeJsonRecord(recordValue(context?.processForm, "formJson")),
    parseMaybeJsonRecord(recordValue(context?.processForm, "formContent")),
    parseMaybeJsonRecord(context?.processFormJson),
    context?.processForm,
    parseMaybeJsonRecord(context?.archivedFormJson),
  ];

  for (const schema of schemas) {
    for (const [name, label] of collectFormFieldLabels(schema)) {
      labels.set(name, label);
    }
  }

  return labels;
}

function normalizeFormData(
  value: unknown,
  fieldLabels = new Map<string, string>(),
): DefectWorkflowHistoryFormValue[] {
  const formData = parseFormData(value);
  const inlineLabels = collectFormFieldLabels(parseJsonRecord(formData.formJson));
  return Object.entries(formData)
    .filter(([name]) => name !== "formJson")
    .map(([name, item]) => ({
      name,
      label: fieldLabels.get(name) ?? inlineLabels.get(name) ?? name,
      value: displayValue(item),
    }));
}

function getSubmissionId(submission: Record<string, unknown>, index: number): string {
  return stringValue(submission.submissionId) ?? stringValue(submission.taskId) ?? String(index);
}

export function normalizeDefectWorkflowHistory(
  detail: Partial<DefectWorkflowDetail> | null | undefined,
  options: NormalizeDefectWorkflowHistoryOptions = {},
): DefectWorkflowHistoryEntry[] {
  const submissions = Array.isArray(detail?.submissions) ? detail.submissions : [];
  return submissions
    .filter(isRecord)
    .map((submission, index) => {
      const taskId = stringValue(submission.taskId);
      const labels = taskId
        ? collectContextFieldLabels(options.contextsByTaskId?.[taskId])
        : new Map<string, string>();
      return {
        id: getSubmissionId(submission, index),
        taskId,
        nodeKey: stringValue(submission.nodeKey),
        nodeName: stringValue(submission.nodeName) ?? "已处理节点",
        action: stringValue(submission.action),
        actionLabel: actionLabel(submission.action),
        operatorName: stringValue(submission.submittedByName ?? submission.operatorName),
        occurredAt: stringValue(submission.submittedAt ?? submission.occurredAt),
        summary: stringValue(submission.comment ?? submission.summary),
        formData: normalizeFormData(submission.formData, labels),
      };
    });
}
