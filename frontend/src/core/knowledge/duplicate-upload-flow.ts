/**
 * Duplicate-upload action executor (Task 11). Pure sequencing — no React, no
 * toast, no dialog; the page layer wires the mutations and the feedback.
 *
 * Ordering contract (plan Task 11, frozen): replace = DELETE first (the
 * existing cascade endpoint wipes graph/vector/wiki of the old row), then
 * re-upload — never the other way round, or the upload's derived state would
 * be wiped by the late cascade.
 */
import type { DuplicateAction } from "@/components/workspace/knowledge/duplicate-upload-dialog";
import type { KnowledgeDocument } from "@/core/knowledge/types";

export interface DuplicateActionContext {
  file: File;
  doc: KnowledgeDocument;
  /** Pre-allocated copy name for the keep-both / copy branch (`name (2).ext`). */
  copyName: string;
}

export interface DuplicateFlowDeps {
  deleteDocument: (docId: string) => Promise<unknown>;
  uploadFile: (file: File) => Promise<unknown>;
}

export type DuplicateOutcome = "skipped" | "cancelled" | "replaced" | "copied";

export async function executeDuplicateAction(
  action: DuplicateAction,
  context: DuplicateActionContext,
  deps: DuplicateFlowDeps,
): Promise<DuplicateOutcome> {
  switch (action) {
    case "skip":
      return "skipped";
    case "cancel":
      return "cancelled";
    case "replace":
      await deps.deleteDocument(context.doc.id);
      await deps.uploadFile(context.file);
      return "replaced";
    case "copy": {
      const copy = new File([context.file], context.copyName, { type: context.file.type });
      await deps.uploadFile(copy);
      return "copied";
    }
  }
}
