/**
 * Doc failure notifier (2026-08-31): replaces the sonner-toast hook. The
 * global toaster is viewport-fixed (it can never stay inside the document
 * tab) and its semantics clash with the user-finalized contract (no
 * auto-expiry, hover-to-expand must exclude the ✕, folded ✕ closes all).
 * Detection semantics survive unchanged — announce only transitions into
 * ``failed``, never backfire on first load, dedupe per failure episode,
 * re-announce after a retry — but the output is panel state instead of a
 * toast call: entries persist until dismissed, and a document leaving
 * ``failed`` (retry or deletion) withdraws its entry. ``report`` folds
 * upload-time rejections (empty-file 400, unsupported suffix) into the same
 * in-tab panel.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { useI18n } from "@/core/i18n/hooks";
import type { KnowledgeDocument } from "@/core/knowledge/types";

import { classifyDocError } from "./doc-errors";

export interface DocFailureEntry {
  key: string;
  name: string;
  reason: string;
  /** 有文档行的失败可重试（key 即文档 id）；上传即拒类无行可重试。 */
  retryable: boolean;
}

export function useDocFailureNotifier(documents: KnowledgeDocument[] | undefined) {
  const { t } = useI18n();
  const [failures, setFailures] = useState<DocFailureEntry[]>([]);
  // Failure episodes already announced; a doc leaving ``failed`` clears its
  // record so the NEXT failure re-announces.
  const notified = useRef(new Set<string>());
  const initialized = useRef(false);
  const rejectionSeq = useRef(0);

  useEffect(() => {
    if (!documents) return;
    const tk = t.knowledge.docErrors;
    const byId = new Map(documents.map((doc) => [doc.id, doc]));
    // 文档离开 failed（重试/删除）即撤条——界面只剩状态本身。
    setFailures((prev) =>
      prev.filter((entry) => entry.key.startsWith("rejection-") || byId.get(entry.key)?.status === "failed"),
    );
    for (const doc of documents) {
      if (doc.status !== "failed") notified.current.delete(doc.id);
    }
    if (!initialized.current) {
      // First snapshot: pre-mark existing failures — history never backfires.
      for (const doc of documents) {
        if (doc.status === "failed") notified.current.add(doc.id);
      }
      initialized.current = true;
      return;
    }
    const fresh = documents.filter((doc) => doc.status === "failed" && !notified.current.has(doc.id));
    if (fresh.length === 0) return;
    for (const doc of fresh) notified.current.add(doc.id);
    setFailures((prev) => [
      ...prev,
      ...fresh.map((doc) => ({ key: doc.id, name: doc.name, reason: tk[classifyDocError(doc.error)], retryable: true })),
    ]);
  }, [documents, t]);

  /** 上传即拒（空文件 400、格式不支持）不落文档行，以临时键收编进同一面板。 */
  const report = useCallback((name: string, reason: string) => {
    rejectionSeq.current += 1;
    const key = `rejection-${rejectionSeq.current}`;
    setFailures((prev) => [...prev, { key, name, reason, retryable: false }]);
  }, []);

  const dismissOne = useCallback((key: string) => {
    setFailures((prev) => prev.filter((entry) => entry.key !== key));
  }, []);

  const dismissAll = useCallback(() => setFailures([]), []);

  return { failures, report, dismissOne, dismissAll };
}
