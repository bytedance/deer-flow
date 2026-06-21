export interface DefectWorkflowApiEnvelope<T> {
  code?: number | string;
  msg?: string;
  message?: string;
  data?: T;
}

export interface DefectWorkflowPage<T> {
  rows: T[];
  total?: number;
  pageNo?: number;
  pageSize?: number;
  resultSource?: string;
}

export interface DefectWorkflowTodoParams {
  pageNo?: number;
  pageSize?: number;
  [key: string]: string | number | boolean | undefined;
}

export interface DefectEquipment {
  id?: string | number;
  deviceId?: string | number;
  equipmentId?: string | number;
  name?: string;
  deviceName?: string;
  equipmentName?: string;
  code?: string;
  [key: string]: unknown;
}

export interface DefectSummary {
  id?: string | number;
  defectId?: string | number;
  code?: string;
  defectCode?: string;
  defectNo?: string;
  title?: string;
  name?: string;
  description?: string;
  severity?: string;
  status?: string;
  equipment?: DefectEquipment | null;
  deviceId?: string | number;
  equipmentId?: string | number;
  equipmentCode?: string;
  equipmentName?: string;
  areaName?: string;
  createdAt?: string;
  createTime?: string;
  updatedAt?: string;
  [key: string]: unknown;
}

export interface DefectWorkflowTask {
  taskId: string | number;
  nodeKey?: string;
  nodeName?: string;
  formKey?: string;
  formVersion?: string | number;
  allowedActions?: string[];
  assignee?: string | number | null;
  assignedToCurrentUser?: boolean;
  candidateForCurrentUser?: boolean;
  claimRequired?: boolean;
  claimable?: boolean;
  claimedByCurrentUser?: boolean;
  [key: string]: unknown;
}

export interface DefectWorkflowTodoRow extends DefectWorkflowTask {
  defect: DefectSummary;
}

export interface DefectWorkflowDetail {
  defect?: DefectSummary;
  workflowBinding?: Record<string, unknown> | null;
  currentTask?: DefectWorkflowTask | null;
  submissions?: unknown[];
  nodeDetails?: unknown[];
  operationLogs?: unknown[];
  timeline?: unknown[];
  processView?: unknown;
  [key: string]: unknown;
}

export interface VFormOptionItem {
  label?: string;
  value?: unknown;
  name?: string;
  text?: string;
  [key: string]: unknown;
}

export interface VFormWidgetOptions {
  name?: string;
  fieldName?: string;
  label?: string;
  title?: string;
  placeholder?: string;
  required?: boolean;
  defaultValue?: unknown;
  optionItems?: VFormOptionItem[];
  min?: number;
  max?: number;
  [key: string]: unknown;
}

export interface VFormWidget {
  id?: string;
  key?: string;
  type?: string;
  name?: string;
  options?: VFormWidgetOptions;
  widgetList?: VFormWidget[];
  [key: string]: unknown;
}

export interface WorkflowTaskFormContext {
  businessMetadata?: {
    allowedActions?: string[];
    [key: string]: unknown;
  };
  formSchema?: {
    widgetList?: VFormWidget[];
    [key: string]: unknown;
  };
  form?: {
    widgetList?: VFormWidget[];
    [key: string]: unknown;
  };
  widgetList?: VFormWidget[];
  formData?: Record<string, unknown>;
  effectiveFormData?: Record<string, unknown>;
  variables?: Record<string, unknown>;
  allowedActions?: string[];
  [key: string]: unknown;
}

export interface DefectWorkflowFormOption {
  label: string;
  value: string;
  rawValue: unknown;
}

export interface DefectWorkflowFormField {
  name: string;
  type: "text" | "number" | "textarea" | "select" | "checkbox" | "radio" | "date" | "month" | "multi-select";
  label: string;
  placeholder?: string;
  required: boolean;
  options?: DefectWorkflowFormOption[];
  validation?: {
    min?: number;
    max?: number;
  };
}

export interface UnsupportedWorkflowWidget {
  type: string;
  name?: string;
  label?: string;
  required: boolean;
}

export interface DefectWorkflowFormModel {
  fields: DefectWorkflowFormField[];
  defaultValues: Record<string, unknown>;
  unsupportedWidgets: UnsupportedWorkflowWidget[];
  hasBlockingUnsupportedRequired: boolean;
}

export interface SubmitDefectWorkflowTaskRequest {
  action: string;
  formData: Record<string, unknown>;
  comment?: string;
}
