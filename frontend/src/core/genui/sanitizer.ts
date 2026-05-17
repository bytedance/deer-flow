import DOMPurify from "isomorphic-dompurify";

const ALLOWED_PROPS_BY_COMPONENT: Record<string, Set<string>> = {
  chart: new Set([
    "chart_type", "title", "subtitle", "x_key", "y_key", "data",
    "series", "colors", "x_label", "y_label", "legend", "stacked",
  ]),
  echart: new Set([
    "option", "height", "theme", "loading",
  ]),
  table: new Set([
    "columns", "data", "title", "sortable", "paginated", "page_size",
    "onRowSelect",
  ]),
  card: new Set([
    "title", "value", "subtitle", "trend", "icon", "color",
  ]),
  form: new Set([
    "title", "description", "fields", "submit_label", "cancel_label",
    "default_values",
  ]),
  confirm: new Set([
    "title", "message", "confirm_label", "cancel_label", "variant",
  ]),
  code: new Set([
    "code", "language", "title", "executable", "filename",
  ]),
  timeline: new Set([
    "title", "events", "orientation",
  ]),
  layout: new Set([
    "layout_type", "columns", "gap", "align",
  ]),
  markdown: new Set([
    "content", "title",
  ]),
  // EHM industrial primitives.
  gauge: new Set([
    "value", "min", "max", "unit", "label", "thresholds", "precision",
  ]),
  alarm: new Set([
    "title", "items",
  ]),
  metric: new Set([
    "tag", "label", "value", "unit", "precision", "setpoint", "range",
    "delta", "status",
  ]),
  status: new Set([
    "status", "tag", "label",
  ]),
};

function sanitizeValue(value: unknown, depth = 0): unknown {
  if (typeof value === "function") {
    return undefined;
  }
  if (depth > 20) return value;
  if (typeof value === "string") {
    return DOMPurify.sanitize(value, { ALLOWED_TAGS: [], ALLOWED_ATTR: [] });
  }
  if (Array.isArray(value)) {
    return value.map((v) => sanitizeValue(v, depth + 1));
  }
  if (typeof value === "object" && value !== null) {
    const sanitized: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value)) {
      sanitized[k] = sanitizeValue(v, depth + 1);
    }
    return sanitized;
  }
  return value;
}

function isValidOption(opt: unknown): boolean {
  if (typeof opt !== "object" || opt === null) return false;
  const o = opt as Record<string, unknown>;
  return typeof o.label === "string" && o.label !== "" &&
    typeof o.value === "string" && o.value !== "";
}

function isValidField(field: unknown): boolean {
  if (typeof field !== "object" || field === null) return false;
  const f = field as Record<string, unknown>;
  return typeof f.name === "string" && typeof f.type === "string";
}

function sanitizeFormFields(fields: unknown): unknown {
  if (!Array.isArray(fields)) return fields;
  return fields
    .filter(isValidField)
    .map((field) => {
      const f = field as Record<string, unknown>;
      if (Array.isArray(f.options)) {
        return { ...f, options: f.options.filter(isValidOption) };
      }
      return field;
    });
}

export function sanitizeProps(
  component: string,
  props: Record<string, unknown>,
): Record<string, unknown> {
  const allowedKeys = ALLOWED_PROPS_BY_COMPONENT[component];
  if (!allowedKeys) {
    return {};
  }

  const sanitized: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(props)) {
    if (allowedKeys.has(key)) {
      sanitized[key] = sanitizeValue(value);
    }
  }

  if (component === "form" && Array.isArray(sanitized.fields)) {
    sanitized.fields = sanitizeFormFields(sanitized.fields);
  }

  return sanitized;
}
