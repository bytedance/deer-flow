import DOMPurify from "isomorphic-dompurify";

const ALLOWED_PROPS_BY_COMPONENT: Record<string, Set<string>> = {
  chart: new Set([
    "chart_type", "title", "subtitle", "x_key", "y_key", "data",
    "series", "colors", "x_label", "y_label", "legend", "stacked",
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
};

function sanitizeValue(value: unknown): unknown {
  if (typeof value === "string") {
    return DOMPurify.sanitize(value, { ALLOWED_TAGS: [], ALLOWED_ATTR: [] });
  }
  if (Array.isArray(value)) {
    return value.map(sanitizeValue);
  }
  if (typeof value === "object" && value !== null) {
    const sanitized: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value)) {
      sanitized[k] = sanitizeValue(v);
    }
    return sanitized;
  }
  return value;
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
  return sanitized;
}
