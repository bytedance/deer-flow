/**
 * Duplicate-upload interception helpers (Task 11). Pure functions over the
 * current KB's document list — no API calls here; the page layer owns the
 * dialog queue and the replace mutation ordering (delete-then-upload).
 *
 * Contract (plan Task 11, frozen):
 * - same name+ext and identical hash → "identical": skip (default) / keep a copy
 * - same name+ext and different or unknown hash → "conflict": replace / keep both
 *   (keep-both uploads under an auto-allocated `name (2).ext`, incrementing)
 * - no same-name match → "clean": normal upload
 */
import type { KnowledgeDocument } from "@/core/knowledge/types";

import { fileSuffix } from "./supported-formats";

export type DuplicateVerdict =
  | { kind: "clean" }
  | { kind: "identical"; doc: KnowledgeDocument }
  | { kind: "conflict"; doc: KnowledgeDocument };

/** Strip the last dotted extension (Path.stem parity — `archive.tar.gz` → `archive.tar`). */
function baseName(filename: string): string {
  const dot = filename.lastIndexOf(".");
  return dot <= 0 ? filename : filename.slice(0, dot);
}

/**
 * Same-name pre-check: base name matches exactly (case-sensitive — the upload
 * name is a display name, not a normalized key) and the extension matches
 * case-insensitively (`report.PDF` ↔ `report.pdf`).
 */
export function findDuplicateByName(
  filename: string,
  documents: readonly KnowledgeDocument[],
): KnowledgeDocument | undefined {
  const wantedBase = baseName(filename);
  const wantedSuffix = fileSuffix(filename);
  return documents.find(
    (document) => baseName(document.name) === wantedBase && fileSuffix(document.name) === wantedSuffix,
  );
}

/**
 * Branch the verdict from the (always computed) fresh file hash. A legacy row
 * with `content_hash === null` can never prove identity, so it falls into
 * "conflict" (the user decides replace / keep-both).
 */
export function verdictForDuplicate(
  duplicate: KnowledgeDocument | undefined,
  fileHash: string,
): DuplicateVerdict {
  if (!duplicate) {
    return { kind: "clean" };
  }
  if (duplicate.content_hash !== null && duplicate.content_hash === fileHash) {
    return { kind: "identical", doc: duplicate };
  }
  return { kind: "conflict", doc: duplicate };
}

/**
 * Allocate a non-conflicting copy name: `name (2).ext`, incrementing until
 * free. `existingNames` should include every current document name of the KB
 * (plus any already-allocated copies within the same batch).
 */
export function nextCopyName(filename: string, existingNames: ReadonlySet<string>): string {
  const base = baseName(filename);
  const suffix = fileSuffix(filename);
  let counter = 2;
  let candidate = `${base} (${counter})${suffix}`;
  while (existingNames.has(candidate)) {
    counter += 1;
    candidate = `${base} (${counter})${suffix}`;
  }
  return candidate;
}

/** SHA-256 hex of a File via WebCrypto (upload pre-check only, spec Task 11). */
export async function computeSha256(file: File): Promise<string> {
  const buffer = await file.arrayBuffer();
  const digest = await crypto.subtle.digest("SHA-256", buffer);
  return Array.from(new Uint8Array(digest))
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}
