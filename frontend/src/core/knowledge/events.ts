import type {
  FailedKnowledgeDocument,
  KnowledgeDataset,
  KnowledgeParsingEvent,
} from "./types";

const EVENT_TYPES = new Set<KnowledgeParsingEvent["type"]>([
  "dataset_parsing_progress",
  "dataset_parsing_completed",
  "dataset_parsing_failed",
]);

function count(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0
    ? value
    : 0;
}

function failedDocuments(value: unknown): FailedKnowledgeDocument[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    if (typeof item !== "object" || item === null) {
      return [];
    }
    const record = item as Record<string, unknown>;
    const id = record.id;
    const name = record.name;
    if (typeof id !== "string" || typeof name !== "string") return [];
    return [{ id, name }];
  });
}

export function parseKnowledgeEvent(
  type: string,
  event: MessageEvent<string>,
): KnowledgeParsingEvent | null {
  if (!EVENT_TYPES.has(type as KnowledgeParsingEvent["type"])) return null;
  try {
    const payload = JSON.parse(event.data) as Record<string, unknown>;
    if (typeof payload.dataset_id !== "string" || !payload.dataset_id) {
      return null;
    }
    if (type === "dataset_parsing_progress") {
      return {
        type,
        datasetId: payload.dataset_id,
        unstartCount: count(payload.unstart_count),
        runningCount: count(payload.running_count),
        cancelCount: count(payload.cancel_count),
        doneCount: count(payload.done_count),
        failCount: count(payload.fail_count),
      };
    }
    if (type === "dataset_parsing_completed") {
      return {
        type,
        datasetId: payload.dataset_id,
        doneCount: count(payload.done_count),
        failCount: count(payload.fail_count),
      };
    }
    return {
      type: "dataset_parsing_failed",
      datasetId: payload.dataset_id,
      failedDocuments: failedDocuments(payload.failed_documents),
    };
  } catch {
    return null;
  }
}

export function applyKnowledgeEventToDatasets(
  datasets: readonly KnowledgeDataset[],
  event: KnowledgeParsingEvent,
): KnowledgeDataset[] {
  return datasets.map((dataset) => {
    if (dataset.id !== event.datasetId) return dataset;
    if (event.type === "dataset_parsing_progress") {
      return {
        ...dataset,
        unstart_count: event.unstartCount,
        running_count: event.runningCount,
        cancel_count: event.cancelCount,
        done_count: event.doneCount,
        fail_count: event.failCount,
      };
    }
    if (event.type === "dataset_parsing_completed") {
      return {
        ...dataset,
        unstart_count: 0,
        running_count: 0,
        done_count: event.doneCount,
        fail_count: event.failCount,
      };
    }
    return {
      ...dataset,
      running_count: 0,
      fail_count: Math.max(
        count(dataset.fail_count),
        event.failedDocuments.length,
      ),
    };
  });
}
