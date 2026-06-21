import type {
  DefectWorkflowFormField,
  DefectWorkflowFormModel,
  DefectWorkflowFormOption,
  UnsupportedWorkflowWidget,
  VFormWidget,
  WorkflowTaskFormContext,
} from "./types";

const SUPPORTED_TYPES = new Set([
  "input",
  "textarea",
  "number",
  "select",
  "radio",
  "checkbox",
  "switch",
  "date",
  "month",
]);

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function recordValue(value: unknown, key: string): unknown {
  return isObject(value) ? value[key] : undefined;
}

function parseJsonRecord(value: unknown): Record<string, unknown> {
  if (isObject(value)) return value;
  if (typeof value !== "string" || !value.trim()) return {};
  try {
    const parsed = JSON.parse(value) as unknown;
    return isObject(parsed) ? parsed : {};
  } catch {
    return {};
  }
}

function flattenWidgets(widgets: VFormWidget[] | undefined): VFormWidget[] {
  if (!widgets?.length) return [];
  const result: VFormWidget[] = [];
  for (const widget of widgets) {
    result.push(widget);
    if (Array.isArray(widget.widgetList)) {
      result.push(...flattenWidgets(widget.widgetList));
    }
  }
  return result;
}

function getWidgets(context: WorkflowTaskFormContext | null | undefined): VFormWidget[] {
  if (!context) return [];
  const schemas: unknown[] = [
    context.formSchema,
    parseJsonRecord(recordValue(context.form, "formJson")),
    parseJsonRecord(recordValue(context.form, "formContent")),
    context.form,
    parseJsonRecord(context.formContent),
    context.widgetList ? { widgetList: context.widgetList } : undefined,
  ];

  for (const schema of schemas) {
    if (!isObject(schema) || !Array.isArray(schema.widgetList)) continue;
    const widgets = flattenWidgets(schema.widgetList as VFormWidget[]);
    if (widgets.length > 0) return widgets;
  }

  return [];
}

function getFieldName(widget: VFormWidget): string | undefined {
  const options = widget.options ?? {};
  const raw =
    options.name ??
    options.fieldName ??
    widget.name ??
    widget.key ??
    widget.id;
  return raw ? String(raw) : undefined;
}

function getFieldLabel(widget: VFormWidget, name?: string): string {
  const options = widget.options ?? {};
  return String(options.label ?? options.title ?? name ?? "未命名字段");
}

function isRequired(widget: VFormWidget): boolean {
  const options = widget.options ?? {};
  if (typeof options.required === "boolean") return options.required;
  const validation = options.validation;
  return isObject(validation) && validation.required === true;
}

function getOptionItems(widget: VFormWidget): DefectWorkflowFormOption[] {
  const items = widget.options?.optionItems;
  if (!Array.isArray(items)) return [];
  return items.map((item, index) => {
    const rawValue = item.value ?? item.name ?? item.label ?? item.text ?? index;
    const label = String(item.label ?? item.name ?? item.text ?? rawValue);
    return {
      label,
      value: String(rawValue),
      rawValue,
    };
  });
}

function mapWidgetType(widget: VFormWidget): DefectWorkflowFormField["type"] | null {
  const type = String(widget.type ?? "").toLowerCase();
  switch (type) {
    case "input":
      return "text";
    case "textarea":
      return "textarea";
    case "number":
      return "number";
    case "select":
      return "select";
    case "radio":
      return "radio";
    case "checkbox":
      return getOptionItems(widget).length > 0 ? "multi-select" : "checkbox";
    case "switch":
      return "checkbox";
    case "date":
      return "date";
    case "month":
      return "month";
    default:
      return null;
  }
}

function lookupDefaultValue(
  name: string,
  widget: VFormWidget,
  context: WorkflowTaskFormContext,
): unknown {
  const sources = [
    context.effectiveFormData,
    context.formData,
    context.variables,
  ];
  for (const source of sources) {
    if (source && Object.prototype.hasOwnProperty.call(source, name)) {
      return source[name];
    }
  }
  return widget.options?.defaultValue;
}

function normalizeDefaultValue(
  field: DefectWorkflowFormField,
  rawValue: unknown,
): unknown {
  if (rawValue === undefined) {
    if (field.type === "checkbox") return false;
    if (field.type === "multi-select") return [];
    return "";
  }
  if (field.type === "checkbox") return Boolean(rawValue);
  if (field.type === "multi-select") {
    return Array.isArray(rawValue) ? rawValue : [];
  }
  if (field.type === "number" && rawValue !== "") {
    const n = Number(rawValue);
    return Number.isNaN(n) ? rawValue : n;
  }
  return rawValue;
}

function toUnsupported(widget: VFormWidget): UnsupportedWorkflowWidget {
  const name = getFieldName(widget);
  return {
    type: String(widget.type ?? "unknown"),
    name,
    label: getFieldLabel(widget, name),
    required: isRequired(widget),
  };
}

export function convertVFormContextToFormModel(
  context: WorkflowTaskFormContext | null | undefined,
): DefectWorkflowFormModel {
  const safeContext = context ?? {};
  const fields: DefectWorkflowFormField[] = [];
  const defaultValues: Record<string, unknown> = {};
  const unsupportedWidgets: UnsupportedWorkflowWidget[] = [];

  for (const widget of getWidgets(safeContext)) {
    const rawType = String(widget.type ?? "").toLowerCase();
    const name = getFieldName(widget);
    if (!rawType || !name || !SUPPORTED_TYPES.has(rawType)) {
      unsupportedWidgets.push(toUnsupported(widget));
      continue;
    }

    const mappedType = mapWidgetType(widget);
    if (!mappedType) {
      unsupportedWidgets.push(toUnsupported(widget));
      continue;
    }

    const field: DefectWorkflowFormField = {
      name,
      type: mappedType,
      label: getFieldLabel(widget, name),
      placeholder: widget.options?.placeholder,
      required: isRequired(widget),
      options: getOptionItems(widget),
      validation: {
        min: widget.options?.min,
        max: widget.options?.max,
      },
    };
    fields.push(field);
    defaultValues[name] = normalizeDefaultValue(
      field,
      lookupDefaultValue(name, widget, safeContext),
    );
  }

  return {
    fields,
    defaultValues,
    unsupportedWidgets,
    hasBlockingUnsupportedRequired: unsupportedWidgets.some((w) => w.required),
  };
}
