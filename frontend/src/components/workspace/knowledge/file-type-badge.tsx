"use client";

/**
 * File-type icons, exported from the Ardot library 「组件库」 (file
 * 720819382141740). Geometry is the 56-grid masters in frame
 * 「图标组件库 · FileType Icons」; each category's color pair and suffix list
 * come from frame 「01 分类色板与图标」. Shape carries the type, color carries
 * the family, so the badge renders no text at all.
 *
 * Coordinates are kept exactly as the canvas exports them (including the
 * per-node `transform`) so a future re-export diffs cleanly against this
 * file. Rectangles stay `<rect rx>` because that is what the design stores,
 * even though the SVG exporter renders them as outline paths.
 *
 * To change a color or move a suffix between categories, edit the design file
 * first — it is the authority — then re-export and sync `KIND_BY_SUFFIX`.
 */

import type { ReactNode } from "react";

import { fileSuffix } from "@/core/knowledge/supported-formats";

export type FileTypeKind =
  | "pdf"
  | "word"
  | "ppt"
  | "sheet"
  | "code"
  | "image"
  | "media"
  | "archive"
  | "unknown";

/** Suffix → category, per the design file's per-row 格式 lists. Suffixes the
 * upload allowlist does not accept yet (archives, media, most images) are
 * mapped anyway so the icons light up as soon as parsing supports them. */
const KIND_BY_SUFFIX: Record<string, FileTypeKind> = {
  // 文档 #2563EB
  ".doc": "word",
  ".docx": "word",
  ".wps": "word",
  ".pages": "word",
  ".rtf": "word",
  ".txt": "word",
  // 表格 #16A34A
  ".xls": "sheet",
  ".xlsx": "sheet",
  ".csv": "sheet",
  ".tsv": "sheet",
  ".numbers": "sheet",
  ".et": "sheet",
  // 演示 #F97316
  ".ppt": "ppt",
  ".pptx": "ppt",
  ".key": "ppt",
  ".dps": "ppt",
  // PDF #DC2626
  ".pdf": "pdf",
  // 代码与数据 #0891B2 — Markdown 归此类，不与 .docx 共用蓝色文档图标
  ".md": "code",
  ".markdown": "code",
  ".json": "code",
  ".yaml": "code",
  ".xml": "code",
  ".py": "code",
  ".js": "code",
  ".sql": "code",
  // 图片 #8B5CF6
  ".jpg": "image",
  ".jpeg": "image",
  ".png": "image",
  ".gif": "image",
  ".webp": "image",
  ".svg": "image",
  ".bmp": "image",
  // 音视频 #EC4899
  ".mp4": "media",
  ".mov": "media",
  ".avi": "media",
  ".mkv": "media",
  ".mp3": "media",
  ".wav": "media",
  // 压缩包 #B45309
  ".zip": "archive",
  ".rar": "archive",
  ".7z": "archive",
  ".tar": "archive",
  ".gz": "archive",
};

/** Lowercase dotted suffix → badge kind; unmapped suffixes stay generic. */
export function fileTypeKind(fileName: string): FileTypeKind {
  return KIND_BY_SUFFIX[fileSuffix(fileName)] ?? "unknown";
}

/** Paper sheet with a folded corner — shared skeleton of 7 of the 9 icons. */
const SHEET_D =
  "M7 0L28 0L39.6667 11.6667L39.6667 39.6667C39.6667 43.54 36.54 46.6667 32.6667 46.6667L7 46.6667C3.1267 46.6667 0 43.54 0 39.6667L0 7C0 3.1267 3.1267 0 7 0Z";
const FOLD_D = "M0 0L11.6667 11.6667L0 11.6667L0 0Z";

function Sheet({ fold, shell }: { fold: string; shell: string }) {
  return (
    <>
      <path
        d={SHEET_D}
        fill={shell}
        transform="matrix(1 0 0 1 4.66667 4.66667)"
      />
      <path
        d={FOLD_D}
        fill={fold}
        transform="matrix(1 0 0 1 32.6667 4.66667)"
      />
    </>
  );
}

const ICON_BY_KIND: Record<FileTypeKind, ReactNode> = {
  pdf: (
    <>
      <Sheet fold="#B91C1C" shell="#DC2626" />
      {/* 字母 P，Sarasa Gothic SC Bold 24 已在画布转成轮廓 */}
      <path
        d="M1.584 21L1.584 3.528L8.4 3.528Q10.392 3.528 11.784 4.296Q13.176 5.04 13.896 6.384Q14.64 7.704 14.64 9.432Q14.64 11.16 13.896 12.48Q13.152 13.8 11.736 14.544Q10.32 15.288 8.304 15.288L5.16 15.288L5.16 21L1.584 21M5.16 12.408L7.728 12.408Q9.384 12.408 10.152 11.592Q10.944 10.752 10.944 9.432Q10.944 8.112 10.152 7.32Q9.384 6.504 7.728 6.504L5.16 6.504L5.16 12.408Z"
        fill="#FFF"
        transform="matrix(1 0 0 1 17 24)"
      />
    </>
  ),
  word: (
    <>
      <Sheet fold="#1E40AF" shell="#2563EB" />
      <rect
        fill="#FFF"
        height="3.9667"
        rx="1.9833"
        width="24.7333"
        x="12.1333"
        y="26.6"
      />
      <rect
        fill="#FFF"
        height="3.9667"
        rx="1.9833"
        width="24.7333"
        x="12.1333"
        y="34.7667"
      />
      <rect
        fill="#FFF"
        height="3.9667"
        rx="1.9833"
        width="14.9333"
        x="12.1333"
        y="42.9333"
      />
    </>
  ),
  sheet: (
    <>
      <Sheet fold="#15803D" shell="#16A34A" />
      <rect
        fill="#FFF"
        height="3.5"
        rx="1.75"
        width="24.7333"
        x="12.1333"
        y="25.6667"
      />
      <rect
        fill="#FFF"
        height="3.5"
        rx="1.75"
        width="24.7333"
        x="12.1333"
        y="34.0667"
      />
      <rect
        fill="#FFF"
        height="3.5"
        rx="1.75"
        width="24.7333"
        x="12.1333"
        y="42.4667"
      />
      <rect
        fill="#FFF"
        height="20.3"
        rx="1.75"
        width="3.5"
        x="20.0667"
        y="25.6667"
      />
      <rect
        fill="#FFF"
        height="20.3"
        rx="1.75"
        width="3.5"
        x="28.4667"
        y="25.6667"
      />
    </>
  ),
  ppt: (
    <>
      <Sheet fold="#C2410C" shell="#F97316" />
      <rect
        fill="#FFF"
        height="20.5333"
        rx="3.2667"
        width="27.5333"
        x="10.7333"
        y="24.2667"
      />
      <rect
        fill="#F97316"
        height="3.7333"
        rx="1.8667"
        width="10.7333"
        x="14.4667"
        y="28.4667"
      />
      <rect
        fill="#F97316"
        height="2.8"
        opacity="0.45"
        rx="1.4"
        width="20.0667"
        x="14.4667"
        y="34.7667"
      />
      <rect
        fill="#F97316"
        height="2.8"
        opacity="0.45"
        rx="1.4"
        width="14"
        x="14.4667"
        y="39.4333"
      />
    </>
  ),
  code: (
    <>
      <Sheet fold="#0E7490" shell="#0891B2" />
      <path
        d="M7.2333 0L0 6.5333L7.2333 13.0667L9.5667 10.7333L4.2 6.5333L9.5667 2.3333L7.2333 0Z"
        fill="#FFF"
        transform="matrix(1 0 0 1 14.2333 24.2667)"
      />
      <path
        d="M2.3333 0L9.5667 6.5333L2.3333 13.0667L0 10.7333L5.3667 6.5333L0 2.3333L2.3333 0Z"
        fill="#FFF"
        transform="matrix(1 0 0 1 25.2 24.2667)"
      />
    </>
  ),
  image: (
    <>
      <rect
        fill="#8B5CF6"
        height="37.3333"
        rx="7"
        width="44.3333"
        x="5.8333"
        y="9.3333"
      />
      <circle cx="18.4333" cy="20.0667" fill="#FFF" r="4.2" />
      <path
        d="M0 17.0333L12.6 0L23.3333 12.6L28.4667 7L36.4 17.0333L0 17.0333Z"
        fill="#FFF"
        transform="matrix(1 0 0 1 9.8 28.4667)"
      />
    </>
  ),
  media: (
    <>
      <rect
        fill="#EC4899"
        height="37.3333"
        rx="7"
        width="44.3333"
        x="5.8333"
        y="9.3333"
      />
      <path
        d="M0 0L12.6 6.5333L0 13.0667L0 0Z"
        fill="#FFF"
        transform="matrix(1 0 0 1 23.3333 21.4667)"
      />
    </>
  ),
  archive: (
    <>
      <Sheet fold="#92400E" shell="#B45309" />
      <rect
        fill="#FFF"
        height="21.9333"
        rx="1.8667"
        width="3.7333"
        x="24.9667"
        y="22.4"
      />
      <rect
        fill="#FFF"
        height="3.7333"
        rx="1.8667"
        width="16.3333"
        x="17.7333"
        y="30.3333"
      />
      <rect
        fill="#FFF"
        height="3.7333"
        rx="1.8667"
        width="16.3333"
        x="17.7333"
        y="37.3333"
      />
    </>
  ),
  // 未知类型：只有折角页轮廓，不假装有类型信息
  unknown: <Sheet fold="#475569" shell="#64748B" />,
};

/** Design-file icon; pass `className="size-5 shrink-0"` etc. */
export function FileTypeBadge({
  fileName,
  className,
}: {
  fileName: string;
  className?: string;
}) {
  const kind = fileTypeKind(fileName);
  return (
    <svg
      aria-hidden="true"
      className={className}
      data-filetype={kind}
      viewBox="0 0 56 56"
    >
      {ICON_BY_KIND[kind]}
    </svg>
  );
}

// ── Drag-in type probe (2026-09-01) ───────────────────────────────────────
// dragover exposes each dragged item's MIME type (never its contents), which
// is enough to recognize the file family and match it against the upload
// allowlist BEFORE the drop — powering the empty-state nine-grid's
// accept-lights-up / reject-dims feedback.

interface MimeSpec {
  kind: FileTypeKind;
  mimes: string[];
  /** Candidate suffixes for this MIME; accepted if any is in the allowlist. */
  suffixes: string[];
}

const MIME_SPECS: MimeSpec[] = [
  { kind: "pdf", mimes: ["application/pdf"], suffixes: [".pdf"] },
  {
    kind: "word",
    mimes: [
      "application/msword",
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      "application/vnd.apple.pages",
      "application/rtf",
      "text/plain",
    ],
    suffixes: [".doc", ".docx", ".wps", ".pages", ".rtf", ".txt"],
  },
  {
    kind: "sheet",
    mimes: [
      "application/vnd.ms-excel",
      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      "text/csv",
      "text/tab-separated-values",
      "application/vnd.apple.numbers",
    ],
    suffixes: [".xls", ".xlsx", ".csv", ".tsv", ".numbers", ".et"],
  },
  {
    kind: "ppt",
    mimes: [
      "application/vnd.ms-powerpoint",
      "application/vnd.openxmlformats-officedocument.presentationml.presentation",
      "application/vnd.apple.keynote",
    ],
    suffixes: [".ppt", ".pptx", ".key", ".dps"],
  },
  {
    kind: "code",
    mimes: [
      "text/markdown",
      "text/x-markdown",
      "application/json",
      "application/xml",
      "text/xml",
      "text/yaml",
      "text/x-yaml",
      "text/x-python",
      "application/javascript",
      "text/javascript",
      "application/sql",
    ],
    suffixes: [".md", ".markdown", ".json", ".yaml", ".xml", ".py", ".js", ".sql"],
  },
  {
    kind: "archive",
    mimes: [
      "application/zip",
      "application/x-rar-compressed",
      "application/x-7z-compressed",
      "application/x-tar",
      "application/gzip",
    ],
    suffixes: [".zip", ".rar", ".7z", ".tar", ".gz"],
  },
];

function specForMime(mime: string): MimeSpec | null {
  if (!mime) return null;
  const direct = MIME_SPECS.find((spec) => spec.mimes.includes(mime));
  if (direct) return direct;
  // Families without a fixed member list: prefix-match.
  if (mime.startsWith("image/")) {
    return {
      kind: "image",
      mimes: [],
      suffixes: [".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp"],
    };
  }
  if (mime.startsWith("audio/") || mime.startsWith("video/")) {
    return {
      kind: "media",
      mimes: [],
      suffixes: [".mp4", ".mov", ".avi", ".mkv", ".mp3", ".wav"],
    };
  }
  return null;
}

/** MIME → badge kind; null for empty/unrecognized types. */
export function kindFromMime(mime: string): FileTypeKind | null {
  return specForMime(mime)?.kind ?? null;
}

export interface DragProbe {
  /** Badge kinds of the accepted dragged files (the ones that light up). */
  litKinds: FileTypeKind[];
  anyAccepted: boolean;
  anyRejected: boolean;
}

/**
 * Verdict for the files currently hovering over the panel. ArrayLike covers
 * both the real `DataTransferItemList` and plain test fixtures; non-file
 * items (dragged text/links) are ignored rather than counted either way.
 * Unrecognized MIME types count as rejected — lighting an icon the drop
 * would then refuse is worse than staying dim.
 */
export function probeDraggedItems(
  items: ArrayLike<{ kind: string; type: string }> | null | undefined,
  supportedSuffixes: readonly string[],
): DragProbe {
  const lit = new Set<FileTypeKind>();
  let anyAccepted = false;
  let anyRejected = false;
  if (items) {
    for (const item of Array.from(items)) {
      if (item.kind !== "file") continue;
      const spec = specForMime(item.type);
      const accepted =
        spec?.suffixes.some((suffix) => supportedSuffixes.includes(suffix)) ?? false;
      if (accepted && spec) {
        lit.add(spec.kind);
        anyAccepted = true;
      } else {
        anyRejected = true;
      }
    }
  }
  return { litKinds: [...lit], anyAccepted, anyRejected };
}

/** Stable key of a probe — dragover fires constantly, only a changed probe
 * should trigger a re-render. */
export function probeSignature(probe: DragProbe | null): string {
  if (!probe) return "";
  return `${probe.litKinds.join(",")}|${probe.anyAccepted ? 1 : 0}|${probe.anyRejected ? 1 : 0}`;
}
