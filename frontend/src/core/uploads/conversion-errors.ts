/**
 * Conversion error → user-facing toast text.
 *
 * Backend (`packages/harness/deerflow/utils/file_conversion.py`) returns a
 * 422 with body `{code, message, filename}` when document conversion fails.
 * The frontend keys off `code` so the toast text is localised on this side
 * — backend `message` is English-only and meant for logs / admins.
 *
 * Adding a new code: keep the backend `ConversionErrorCode` enum and this
 * map in lockstep. The default branch falls back to a generic
 * "conversion failed" so a backend-only addition doesn't crash the UI.
 */

export type ConversionErrorCode =
  | "EMPTY_RESULT"
  | "ENCRYPTED_PDF"
  | "UNSUPPORTED_FORMAT"
  | "MARKITDOWN_UNAVAILABLE"
  | "OCR_UNAVAILABLE"
  | "INTERNAL_ERROR";

export interface ConversionErrorBody {
  code: ConversionErrorCode | string;
  message?: string;
  filename?: string;
}

export class ConversionError extends Error {
  readonly code: ConversionErrorCode | string;
  readonly filename?: string;
  readonly serverMessage?: string;

  constructor(body: ConversionErrorBody) {
    super(body.message ?? "Conversion failed");
    this.name = "ConversionError";
    this.code = body.code;
    this.filename = body.filename;
    this.serverMessage = body.message;
  }
}

const TOAST_TEXT_EN: Record<ConversionErrorCode, string> = {
  EMPTY_RESULT:
    "The document looks image-based or scanned — we could not extract any text. Please run OCR locally and re-upload as text.",
  ENCRYPTED_PDF:
    "This PDF is password-protected. Remove the password and re-upload.",
  UNSUPPORTED_FORMAT:
    "This file type is not supported. Convert to PDF / DOCX / XLSX / PPTX first.",
  MARKITDOWN_UNAVAILABLE:
    "The server's MarkItDown converter is not installed. Ask your administrator to install `markitdown`.",
  OCR_UNAVAILABLE:
    "OCR engine not installed on server. Ask your administrator to install Tesseract (tesseract-ocr).",
  INTERNAL_ERROR:
    "We could not convert this document. Try a different file, or contact support if it keeps failing.",
};

const TOAST_TEXT_ZH: Record<ConversionErrorCode, string> = {
  EMPTY_RESULT:
    "文档看起来是扫描件/图片版,无法提取文字。请先本地 OCR 后再以文本方式上传。",
  ENCRYPTED_PDF: "这份 PDF 已加密,请先移除密码再上传。",
  UNSUPPORTED_FORMAT:
    "暂不支持此文件类型,请先转为 PDF / DOCX / XLSX / PPTX 后再上传。",
  MARKITDOWN_UNAVAILABLE:
    "服务器未安装 MarkItDown 转换器,请联系管理员安装 `markitdown`。",
  OCR_UNAVAILABLE:
    "服务器未安装 OCR 引擎,请联系管理员安装 Tesseract (tesseract-ocr)。",
  INTERNAL_ERROR: "文档转换失败,请换个文件再试,或联系管理员。",
};

export function conversionErrorToastText(
  code: ConversionErrorCode | string,
  locale: "en-US" | "zh-CN" = "en-US",
  filename?: string,
): string {
  const table = locale === "zh-CN" ? TOAST_TEXT_ZH : TOAST_TEXT_EN;
  const base =
    (table as Record<string, string>)[code] ??
    (locale === "zh-CN"
      ? "文档转换失败,请重试。"
      : "Conversion failed. Please try again.");
  return filename ? `${filename}: ${base}` : base;
}
