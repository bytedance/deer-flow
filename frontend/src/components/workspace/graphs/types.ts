import type { EChartsOption } from "echarts";

export interface ChartConfig {
  id: string;
  title: string;
  option: EChartsOption;
  datasetIndex?: number;
}

export interface MetricCard {
  id: string;
  label: string;
  value: string;
  change?: string;
}

export interface DatasetInfo {
  id: string;
  fileName: string;
  rowCount: number;
  columns: { name: string; type: string }[];
}

export interface QueryResult {
  sql: string;
  label: string;
  data: Record<string, unknown>[];
  rowCount: number;
  source?: "sql" | "ai";
}

export interface ArtifactGroup {
  id: string;
  type?: "graph";
  title: string;
  charts: ChartConfig[];
  metrics: MetricCard[];
  data?: Record<string, unknown>[];
  queryResult?: QueryResult;
  queryResults?: QueryResult[];
}

export type Artifact = ArtifactGroup;

export interface Page {
  id: string;
  name: string;
  artifact: ArtifactGroup;
  createdAt: number;
}
