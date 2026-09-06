export const KNOWLEDGE_SCOPE_KEY = "knowledge_scope";

const MAX_DATASETS = 100;
const MAX_DOCUMENTS = 1000;
const MAX_DISPLAY_DATASETS = 20;
const MAX_DISPLAY_DOCUMENTS = 50;
const MAX_ID_LENGTH = 256;
const MAX_NAME_LENGTH = 256;
const MAX_SCOPE_BYTES = 64 * 1024;

export type KnowledgeScopeDocument = { id: string; name: string };

export type KnowledgeScopeDatasetSelection = {
  id: string;
  name: string;
  documents:
    | { mode: "all" }
    | { mode: "selected"; items: KnowledgeScopeDocument[] };
};

export type KnowledgeScopeSelection =
  | { mode: "all" }
  | { mode: "disabled" }
  | { mode: "selected"; datasets: KnowledgeScopeDatasetSelection[] };

export type KnowledgeScopeSnapshot = {
  version: 1;
  mode: "all" | "selected" | "disabled";
  dataset_ids?: string[];
  document_filters?: Array<{ dataset_id: string; document_ids: string[] }>;
  display?: {
    datasets: Array<{
      id: string;
      name: string;
      documents?: KnowledgeScopeDocument[];
    }>;
  };
};

export const ALL_KNOWLEDGE_SCOPE: KnowledgeScopeSelection = { mode: "all" };

export function cloneKnowledgeScopeSelection(
  selection: KnowledgeScopeSelection,
): KnowledgeScopeSelection {
  if (selection.mode !== "selected") return { mode: selection.mode };
  return {
    mode: "selected",
    datasets: selection.datasets.map((dataset) => ({
      ...dataset,
      documents:
        dataset.documents.mode === "all"
          ? { mode: "all" }
          : {
              mode: "selected",
              items: dataset.documents.items.map((document) => ({
                ...document,
              })),
            },
    })),
  };
}

function normalizeId(value: string): string {
  const id = value.trim();
  if (!id || codePointLength(id) > MAX_ID_LENGTH) {
    throw new Error("Knowledge scope contains an invalid identifier.");
  }
  return id;
}

function codePointLength(value: string): number {
  return [...value].length;
}

function stableUnique<T extends { id: string }>(items: readonly T[]): T[] {
  const result: T[] = [];
  const seen = new Set<string>();
  for (const item of items) {
    const id = normalizeId(item.id);
    if (!seen.has(id)) {
      result.push({ ...item, id });
      seen.add(id);
    }
  }
  return result;
}

function byteLength(value: unknown): number {
  return new TextEncoder().encode(JSON.stringify(value)).length;
}

export function buildKnowledgeScopeSnapshot(
  selection: KnowledgeScopeSelection,
): KnowledgeScopeSnapshot {
  if (selection.mode !== "selected") {
    return { version: 1, mode: selection.mode };
  }

  const datasets = stableUnique(selection.datasets);
  if (datasets.length === 0 || datasets.length > MAX_DATASETS) {
    throw new Error(`Select between 1 and ${MAX_DATASETS} knowledge bases.`);
  }

  const documentFilters: NonNullable<
    KnowledgeScopeSnapshot["document_filters"]
  > = [];
  let documentCount = 0;
  for (const dataset of datasets) {
    if (dataset.documents.mode !== "selected") continue;
    const documents = stableUnique(dataset.documents.items);
    if (documents.length === 0) {
      throw new Error("Select at least one document or choose all documents.");
    }
    documentCount += documents.length;
    documentFilters.push({
      dataset_id: dataset.id,
      document_ids: documents.map((document) => document.id),
    });
  }
  if (documentCount > MAX_DOCUMENTS) {
    throw new Error(`Select at most ${MAX_DOCUMENTS} documents.`);
  }

  const snapshot: KnowledgeScopeSnapshot = {
    version: 1,
    mode: "selected",
    dataset_ids: datasets.map((dataset) => dataset.id),
  };
  if (documentFilters.length > 0) {
    snapshot.document_filters = documentFilters;
  }

  const filtersByDataset = new Map(
    documentFilters.map((filter) => [
      filter.dataset_id,
      new Set(filter.document_ids),
    ]),
  );
  let displayedDocuments = 0;
  const displayDatasets: NonNullable<
    NonNullable<KnowledgeScopeSnapshot["display"]>["datasets"]
  > = [];
  for (const dataset of datasets.slice(0, MAX_DISPLAY_DATASETS)) {
    if (
      !dataset.name.trim() ||
      codePointLength(dataset.name) > MAX_NAME_LENGTH
    )
      continue;
    const entry: (typeof displayDatasets)[number] = {
      id: dataset.id,
      name: dataset.name,
    };
    const allowedDocuments = filtersByDataset.get(dataset.id);
    if (allowedDocuments && dataset.documents.mode === "selected") {
      const remaining = MAX_DISPLAY_DOCUMENTS - displayedDocuments;
      const documents = stableUnique(dataset.documents.items)
        .filter(
          (document) =>
            allowedDocuments.has(document.id) &&
            Boolean(document.name.trim()) &&
            codePointLength(document.name) <= MAX_NAME_LENGTH,
        )
        .slice(0, remaining);
      if (documents.length > 0) {
        entry.documents = documents;
        displayedDocuments += documents.length;
      }
    }
    displayDatasets.push(entry);
  }
  if (displayDatasets.length > 0) {
    snapshot.display = { datasets: displayDatasets };
  }

  while (snapshot.display && byteLength(snapshot) > MAX_SCOPE_BYTES) {
    let lastWithDocuments:
      | NonNullable<KnowledgeScopeSnapshot["display"]>["datasets"][number]
      | undefined;
    for (
      let index = snapshot.display.datasets.length - 1;
      index >= 0;
      index -= 1
    ) {
      const candidate = snapshot.display.datasets[index];
      if (candidate?.documents && candidate.documents.length > 0) {
        lastWithDocuments = candidate;
        break;
      }
    }
    if (lastWithDocuments?.documents) {
      lastWithDocuments.documents.pop();
      if (lastWithDocuments.documents.length === 0) {
        delete lastWithDocuments.documents;
      }
    } else {
      snapshot.display.datasets.pop();
    }
    if (snapshot.display.datasets.length === 0) {
      delete snapshot.display;
    }
  }
  if (byteLength(snapshot) > MAX_SCOPE_BYTES) {
    throw new Error("The selected knowledge scope is too large.");
  }
  return snapshot;
}

export function countKnowledgeScopeSelection(
  selection: KnowledgeScopeSelection,
) {
  if (selection.mode !== "selected") {
    return { datasets: 0, documents: 0 };
  }
  return {
    datasets: selection.datasets.length,
    documents: selection.datasets.reduce(
      (total, dataset) =>
        total +
        (dataset.documents.mode === "selected"
          ? dataset.documents.items.length
          : 0),
      0,
    ),
  };
}

export function readKnowledgeScopeSnapshot(
  value: unknown,
): KnowledgeScopeSnapshot | null {
  if (!value || typeof value !== "object") return null;
  const record = value as Record<string, unknown>;
  if (
    record.version !== 1 ||
    (record.mode !== "all" &&
      record.mode !== "selected" &&
      record.mode !== "disabled")
  ) {
    return null;
  }
  if (record.mode !== "selected") {
    return { version: 1, mode: record.mode };
  }
  if (
    !Array.isArray(record.dataset_ids) ||
    record.dataset_ids.length === 0 ||
    record.dataset_ids.some((id) => typeof id !== "string")
  ) {
    return null;
  }
  const rawFilters = record.document_filters;
  if (
    rawFilters !== undefined &&
    (!Array.isArray(rawFilters) ||
      rawFilters.some(
        (filter) =>
          !filter ||
          typeof filter !== "object" ||
          typeof (filter as Record<string, unknown>).dataset_id !== "string" ||
          !Array.isArray(
            (filter as Record<string, unknown>).document_ids,
          ) ||
          (
            (filter as Record<string, unknown>).document_ids as unknown[]
          ).some((id) => typeof id !== "string"),
      ))
  ) {
    return null;
  }

  const snapshot: KnowledgeScopeSnapshot = {
    version: 1,
    mode: "selected",
    dataset_ids: [...record.dataset_ids],
  };
  if (Array.isArray(rawFilters)) {
    snapshot.document_filters = rawFilters.map((filter) => {
      const item = filter as {
        dataset_id: string;
        document_ids: string[];
      };
      return {
        dataset_id: item.dataset_id,
        document_ids: [...item.document_ids],
      };
    });
  }

  const rawDisplay = record.display;
  if (rawDisplay && typeof rawDisplay === "object") {
    const rawDatasets = (rawDisplay as Record<string, unknown>).datasets;
    if (Array.isArray(rawDatasets)) {
      const datasets = rawDatasets.flatMap((dataset) => {
        if (!dataset || typeof dataset !== "object") return [];
        const item = dataset as Record<string, unknown>;
        if (typeof item.id !== "string" || typeof item.name !== "string") {
          return [];
        }
        const displayDataset: NonNullable<
          KnowledgeScopeSnapshot["display"]
        >["datasets"][number] = { id: item.id, name: item.name };
        if (Array.isArray(item.documents)) {
          displayDataset.documents = item.documents.flatMap((document) => {
            if (!document || typeof document !== "object") return [];
            const displayDocument = document as Record<string, unknown>;
            return typeof displayDocument.id === "string" &&
              typeof displayDocument.name === "string"
              ? [{ id: displayDocument.id, name: displayDocument.name }]
              : [];
          });
        }
        return [displayDataset];
      });
      if (datasets.length > 0) snapshot.display = { datasets };
    }
  }
  return snapshot;
}
