import { z } from "zod";

const trendSchema = z.object({
  direction: z.enum(["up", "down", "flat"]),
  value: z.string(),
});

const chartDataPointSchema = z.record(z.union([z.string(), z.number()]));

const chartSeriesSchema = z.object({
  key: z.string(),
  label: z.string().optional(),
  color: z.string().optional(),
});

export const chartPropsSchema = z.object({
  chart_type: z.enum(["bar", "line", "pie", "scatter"]),
  title: z.string().max(200).optional(),
  subtitle: z.string().max(500).optional(),
  x_key: z.string().max(100).optional(),
  y_key: z.string().max(100).optional(),
  data: z.array(chartDataPointSchema).max(10000),
  series: z.array(chartSeriesSchema).max(50).optional(),
  colors: z.array(z.string().max(50)).max(50).optional(),
  x_label: z.string().max(100).optional(),
  y_label: z.string().max(100).optional(),
  legend: z.boolean().optional(),
  stacked: z.boolean().optional(),
});

const tableColumnSchema = z.object({
  key: z.string(),
  label: z.string(),
  sortable: z.boolean().optional(),
  width: z.number().optional(),
  type: z.enum(["text", "image"]).optional(),
});

export const tablePropsSchema = z.object({
  columns: z.array(tableColumnSchema).max(100),
  data: z.array(z.record(z.unknown())).max(10000),
  title: z.string().max(200).optional(),
  sortable: z.boolean().optional(),
  paginated: z.boolean().optional(),
  page_size: z.number().min(1).max(1000).optional(),
  onRowSelect: z.boolean().optional(),
});

export const cardPropsSchema = z.object({
  title: z.string().max(200),
  value: z.union([z.string().max(100), z.number()]),
  subtitle: z.string().max(500).optional(),
  trend: trendSchema.optional(),
  icon: z.string().max(100).optional(),
  color: z.string().max(50).optional(),
});

const formFieldSchema = z.object({
  name: z.string(),
  type: z.enum(["text", "number", "email", "password", "textarea", "select", "checkbox", "radio", "date", "multi-select"]),
  label: z.string(),
  placeholder: z.string().optional(),
  required: z.boolean().optional(),
  options: z.array(z.object({
    label: z.string(),
    value: z.string(),
    group: z.string().optional(),
    description: z.string().optional(),
  })).optional(),
  searchable: z.boolean().optional(),
  max_visible: z.number().min(1).optional(),
  validation: z.object({
    min: z.number().optional(),
    max: z.number().optional(),
    pattern: z.string().optional(),
    message: z.string().optional(),
  }).optional(),
});

export const formPropsSchema = z.object({
  title: z.string().max(200).optional(),
  description: z.string().max(1000).optional(),
  fields: z.array(formFieldSchema).max(50),
  submit_label: z.string().max(100).optional(),
  cancel_label: z.string().max(100).optional(),
  default_values: z.record(z.unknown()).optional(),
});

export const confirmPropsSchema = z.object({
  title: z.string().max(200),
  message: z.string().max(2000),
  confirm_label: z.string().max(100).optional(),
  cancel_label: z.string().max(100).optional(),
  variant: z.enum(["default", "destructive"]).optional(),
});

export const codePropsSchema = z.object({
  code: z.string().max(100000),
  language: z.string().max(50).optional(),
  title: z.string().max(200).optional(),
  executable: z.boolean().optional(),
  filename: z.string().max(255).optional(),
});

const timelineEventSchema = z.object({
  title: z.string(),
  description: z.string().optional(),
  timestamp: z.string().optional(),
  status: z.enum(["completed", "active", "pending"]).optional(),
  icon: z.string().optional(),
});

export const timelinePropsSchema = z.object({
  title: z.string().max(200).optional(),
  events: z.array(timelineEventSchema).max(100),
  orientation: z.enum(["vertical", "horizontal"]).optional(),
});

export const layoutPropsSchema = z.object({
  layout_type: z.enum(["grid", "flex"]),
  columns: z.number().min(1).max(12).optional(),
  gap: z.number().min(0).max(100).optional(),
  align: z.enum(["start", "center", "end", "stretch"]).optional(),
});

export const markdownPropsSchema = z.object({
  content: z.string().max(100000),
  title: z.string().max(200).optional(),
});

export const echartPropsSchema = z.object({
  option: z.record(z.unknown()).refine(
    (val) => JSON.stringify(val).length <= 500_000,
    { message: "option object exceeds 500KB size limit" },
  ),
  height: z.number().min(100).max(2000).optional(),
  theme: z.string().max(50).optional(),
  loading: z.boolean().optional(),
});

const imagePropsSchema = z.object({
  src: z.string().max(2048),
  alt: z.string().max(500).optional(),
  width: z.number().min(1).max(4096).optional(),
  height: z.number().min(1).max(4096).optional(),
  caption: z.string().max(500).optional(),
  fallback: z.string().max(200).optional(),
});

// ─── EHM industrial primitives ──────────────────────────────────────

const gaugeThresholdsSchema = z.object({
  warn: z.number().optional(),
  error: z.number().optional(),
  critical: z.number().optional(),
});

const gaugePropsSchema = z.object({
  value: z.number(),
  min: z.number().optional(),
  max: z.number().optional(),
  unit: z.string().max(50).optional(),
  label: z.string().max(200).optional(),
  thresholds: gaugeThresholdsSchema.optional(),
  precision: z.number().min(0).max(8).optional(),
});

const alarmLevelSchema = z.enum([
  "critical",
  "high",
  "medium",
  "low",
  "journal",
]);

const alarmItemSchema = z.object({
  level: alarmLevelSchema,
  message: z.string().max(2000),
  tag: z.string().max(100).optional(),
  time: z.string().max(64).optional(),
  source: z.string().max(200).optional(),
  acked: z.boolean().optional(),
});

const alarmPropsSchema = z.object({
  title: z.string().max(200).optional(),
  items: z.array(alarmItemSchema).max(500),
});

const statusKindSchema = z.enum([
  "running",
  "stopped",
  "maint",
  "standby",
  "fault",
  "comm-loss",
]);

const metricRangeSchema = z.object({
  ll: z.number().optional(),
  l: z.number().optional(),
  h: z.number().optional(),
  hh: z.number().optional(),
});

const metricDeltaSchema = z.object({
  value: z.union([z.number(), z.string().max(50)]),
  direction: z.enum(["up", "down", "flat"]).optional(),
  vs: z.string().max(50).optional(),
});

const metricPropsSchema = z.object({
  tag: z.string().max(100).optional(),
  label: z.string().max(200).optional(),
  value: z.union([z.number(), z.string().max(100)]),
  unit: z.string().max(50).optional(),
  precision: z.number().min(0).max(8).optional(),
  setpoint: z.number().optional(),
  range: metricRangeSchema.optional(),
  delta: metricDeltaSchema.optional(),
  status: statusKindSchema.optional(),
});

const statusPropsSchema = z.object({
  status: statusKindSchema,
  tag: z.string().max(100).optional(),
  label: z.string().max(200).optional(),
});

// ─── Device selector schemas ──────────────────────────────────────

const deviceQueryParamsSchema = z.object({
  userId: z.string().optional(),
  orgId: z.number().optional(),
  treeType: z.number().optional(),
  typeId: z.number().optional(),
});

const deviceSelectorPropsSchema = z.object({
  title: z.string().max(200).optional(),
  queryParams: deviceQueryParamsSchema.optional(),
});

const deviceSelectorMultiPropsSchema = z.object({
  title: z.string().max(200).optional(),
  queryParams: deviceQueryParamsSchema.optional(),
  maxSelect: z.number().min(1).optional(),
});

const propsSchemas: Record<string, z.ZodType> = {
  chart: chartPropsSchema,
  echart: echartPropsSchema,
  table: tablePropsSchema,
  card: cardPropsSchema,
  form: formPropsSchema,
  confirm: confirmPropsSchema,
  code: codePropsSchema,
  timeline: timelinePropsSchema,
  layout: layoutPropsSchema,
  markdown: markdownPropsSchema,
  image: imagePropsSchema,
  gauge: gaugePropsSchema,
  alarm: alarmPropsSchema,
  metric: metricPropsSchema,
  status: statusPropsSchema,
  "device-selector": deviceSelectorPropsSchema,
  "device-selector-multi": deviceSelectorMultiPropsSchema,
};

export function validateProps(
  component: string,
  props: unknown,
): { success: boolean; error?: string } {
  const schema = propsSchemas[component];
  if (!schema) {
    return { success: false, error: `Unknown component: ${component}` };
  }

  const result = schema.safeParse(props);
  if (result.success) {
    return { success: true };
  }

  return {
    success: false,
    error: result.error.issues.map((i) => `${i.path.join(".")}: ${i.message}`).join("; "),
  };
}
