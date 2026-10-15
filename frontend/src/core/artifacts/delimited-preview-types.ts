export const DELIMITED_INPUT_LIMIT = 1_048_576;
export const DELIMITED_RECORD_LIMIT = 202;
export const DELIMITED_COLUMN_LIMIT = 50;
export const DELIMITED_TIMEOUT_MS = 5_000;

export interface DelimitedPreviewInput {
  content: string;
  delimiter: "," | "\t";
  truncated: boolean;
}

export interface DelimitedPreviewResult {
  rows: string[][];
  columnCount: number;
  limited: boolean;
  unevenRows: boolean;
}

export type DelimitedPreviewResponse =
  | { result: DelimitedPreviewResult }
  | { error: string };
