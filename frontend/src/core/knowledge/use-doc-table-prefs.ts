"use client";

/**
 * 文档表格列偏好的本地持久化（2026-09-02，方案 Task 1）：列显隐 + 时间格式
 * （绝对/相对）+ 大小单位（KB/MB），per-kb 独立。仿 kb-order.ts 的 localStorage
 * 模式（window.localStorage + try/catch + 类型守卫）；键沿用 knowledge 模块前缀 +
 * chat-panel 的 per-kb 惯例：`deerflow.knowledge.doc-table-prefs.{kbId}.v1`。
 * 列偏好是纯 UI 状态、小且个人化，后端不是其真源——脏数据/缺失一律回退默认。
 */
import { useCallback, useEffect, useRef, useState } from "react";

/** 文档表格的列标识（复选框/尾部操作列不在此列——它们是功能列，不可隐藏）。 */
export type ColumnId =
  | "name"
  | "uploader"
  | "status"
  | "createdAt"
  | "size"
  | "chunks";

/** 可隐藏列（用户拍板 2026-09-02，09-03 纳入状态）：顺序与表格列序一致，
 * 「列」总控与表头右键菜单直接遍历本数组。只有名称固定不可隐藏——它是
 * 行的身份标识，隐掉后表格无从辨识；状态原本一同钉死（当时归为核心列），
 * 09-03 按用户要求改为与其他列同一套隐藏逻辑。 */
export const HIDEABLE_COLUMNS: readonly ColumnId[] = [
  "status",
  "uploader",
  "createdAt",
  "size",
  "chunks",
];

export type TimeFormat = "absolute" | "relative";
export type SizeUnit = "kb" | "mb";

export interface DocTablePrefs {
  hidden: ColumnId[];
  timeFormat: TimeFormat;
  sizeUnit: SizeUnit;
}

export const DEFAULT_DOC_TABLE_PREFS: DocTablePrefs = {
  hidden: [],
  timeFormat: "absolute",
  sizeUnit: "kb",
};

export const DOC_TABLE_PREFS_KEY_PREFIX = "deerflow.knowledge.doc-table-prefs.";

function storageKey(kbId: string): string {
  return `${DOC_TABLE_PREFS_KEY_PREFIX}${kbId}.v1`;
}

function isHideableColumn(value: unknown): value is ColumnId {
  return (
    typeof value === "string" &&
    (HIDEABLE_COLUMNS as readonly string[]).includes(value)
  );
}

/** 类型守卫：只接受合法的可隐藏列与枚举，其余回退默认——脏数据不崩溃。 */
function sanitizePrefs(parsed: unknown): DocTablePrefs {
  if (typeof parsed !== "object" || parsed === null) {
    return DEFAULT_DOC_TABLE_PREFS;
  }
  const raw = parsed as Partial<DocTablePrefs>;
  const hidden = Array.isArray(raw.hidden)
    ? raw.hidden.filter(isHideableColumn)
    : [];
  const timeFormat: TimeFormat =
    raw.timeFormat === "relative" ? "relative" : "absolute";
  const sizeUnit: SizeUnit = raw.sizeUnit === "mb" ? "mb" : "kb";
  return { hidden, timeFormat, sizeUnit };
}

/** 读取某库偏好；缺失/脏数据回退默认。 */
export function readDocTablePrefs(kbId: string): DocTablePrefs {
  try {
    const raw = window.localStorage.getItem(storageKey(kbId));
    if (!raw) return DEFAULT_DOC_TABLE_PREFS;
    return sanitizePrefs(JSON.parse(raw));
  } catch {
    // 隐私模式 / 配额 / 脏数据——列偏好是 nicety，永不崩溃。
    return DEFAULT_DOC_TABLE_PREFS;
  }
}

/** 写回某库偏好；隐私模式/配额异常静默。 */
export function writeDocTablePrefs(kbId: string, prefs: DocTablePrefs): void {
  try {
    window.localStorage.setItem(storageKey(kbId), JSON.stringify(prefs));
  } catch {
    // Best effort only.
  }
}

/**
 * 文档表格列偏好 hook（per-kb）。写回用 kbIdRef 锁定「最新 kbId」：切换库时
 * 先重读新库偏好（setPrefs）再触发写回，避免「用旧库偏好写新库键」的 race。
 */
export function useDocTablePrefs(kbId: string): {
  prefs: DocTablePrefs;
  toggleColumn: (id: ColumnId) => void;
  setTimeFormat: (format: TimeFormat) => void;
  setSizeUnit: (unit: SizeUnit) => void;
  resetColumns: () => void;
} {
  const [prefs, setPrefs] = useState<DocTablePrefs>(() =>
    readDocTablePrefs(kbId),
  );
  const kbIdRef = useRef(kbId);

  // 切换库：更新 ref + 重读该库偏好（per-kb 隔离）。
  useEffect(() => {
    kbIdRef.current = kbId;
    setPrefs(readDocTablePrefs(kbId));
  }, [kbId]);

  // 偏好变化：写回当前（最新）库键。用 ref 而非 kbId 依赖，规避切换 race。
  useEffect(() => {
    writeDocTablePrefs(kbIdRef.current, prefs);
  }, [prefs]);

  const toggleColumn = useCallback((id: ColumnId) => {
    setPrefs((current) => ({
      ...current,
      hidden: current.hidden.includes(id)
        ? current.hidden.filter((column) => column !== id)
        : [...current.hidden, id],
    }));
  }, []);

  const setTimeFormat = useCallback((timeFormat: TimeFormat) => {
    setPrefs((current) => ({ ...current, timeFormat }));
  }, []);

  const setSizeUnit = useCallback((sizeUnit: SizeUnit) => {
    setPrefs((current) => ({ ...current, sizeUnit }));
  }, []);

  const resetColumns = useCallback(() => {
    setPrefs((current) => ({ ...current, hidden: [] }));
  }, []);

  return { prefs, toggleColumn, setTimeFormat, setSizeUnit, resetColumns };
}
