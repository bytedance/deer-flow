import type { KnowledgeDocument } from "./types";

export type DocumentSortKey = "created_at" | "name" | "size_bytes" | "chunk_count";
export type SortDirection = "asc" | "desc";

export const DEFAULT_DOCUMENT_SORT: { key: DocumentSortKey; direction: SortDirection } = {
  key: "created_at",
  direction: "desc",
};

/**
 * Case-insensitive name containment filter for the document list toolbar
 * (spec §5.2). The list endpoint returns the full collection, so filtering
 * stays client-side.
 */
export function filterDocuments(
  documents: KnowledgeDocument[],
  query: string,
): KnowledgeDocument[] {
  const needle = query.trim().toLowerCase();
  if (!needle) {
    return documents;
  }
  return documents.filter((doc) => doc.name.toLowerCase().includes(needle));
}

/**
 * Stable client-side sort for the document list. Nullable numeric columns
 * (chunk_count) always sink to the bottom regardless of direction.
 */
export function sortDocuments(
  documents: KnowledgeDocument[],
  key: DocumentSortKey,
  direction: SortDirection,
): KnowledgeDocument[] {
  const sign = direction === "asc" ? 1 : -1;
  return [...documents].sort((a, b) => {
    const av = a[key];
    const bv = b[key];
    if (av == null && bv == null) {
      return 0;
    }
    if (av == null) {
      return 1;
    }
    if (bv == null) {
      return -1;
    }
    if (typeof av === "string" && typeof bv === "string") {
      return sign * av.localeCompare(bv);
    }
    return sign * (Number(av) - Number(bv));
  });
}
