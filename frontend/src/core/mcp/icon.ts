import type { MCPServerConfig } from "./types";

export const MAX_PLUGIN_ICON_FILE_BYTES = 2 * 1024 * 1024;
export const MAX_PLUGIN_ICON_DATA_LENGTH = 100_000;
const ICON_SIZE = 128;
const ALLOWED_TYPES = new Set(["image/png", "image/jpeg", "image/webp"]);

export type PluginIconErrorCode = "type" | "size" | "invalid";
export class PluginIconError extends Error {
  constructor(readonly code: PluginIconErrorCode) {
    super(code);
  }
}

/** Only bounded, inlined PNGs are displayed. Never fetch a config-supplied URL. */
export function safePluginIcon(value: unknown): string | undefined {
  return typeof value === "string" &&
    value.length <= MAX_PLUGIN_ICON_DATA_LENGTH &&
    /^data:image\/png;base64,iVBORw0KGgo[A-Za-z0-9+/]*={0,2}$/.test(value)
    ? value
    : undefined;
}

function presentationOf(config: MCPServerConfig): Record<string, unknown> {
  const value = config.presentation;
  return value && typeof value === "object" && !Array.isArray(value)
    ? value
    : {};
}

export function readPluginIcon(config: MCPServerConfig): string | undefined {
  return safePluginIcon(presentationOf(config).icon);
}

/** Preserve all connection fields and unrelated presentation keys on save/reset. */
export function withPluginIcon(
  config: MCPServerConfig,
  icon: string | null | undefined,
): MCPServerConfig {
  if (icon === undefined) return config;
  const presentation = { ...presentationOf(config) };
  if (icon === null) delete presentation.icon;
  else {
    const safe = safePluginIcon(icon);
    if (!safe) throw new PluginIconError("invalid");
    presentation.icon = safe;
  }
  const result = { ...config };
  if (Object.keys(presentation).length) result.presentation = presentation;
  else delete result.presentation;
  return result;
}

/** Decode a local raster image and persist a small, square PNG without metadata. */
export async function preparePluginIcon(file: File): Promise<string> {
  if (!ALLOWED_TYPES.has(file.type)) throw new PluginIconError("type");
  if (file.size > MAX_PLUGIN_ICON_FILE_BYTES) throw new PluginIconError("size");
  const header = new Uint8Array(await file.slice(0, 12).arrayBuffer());
  const png = [137, 80, 78, 71, 13, 10, 26, 10].every(
    (byte, index) => header[index] === byte,
  );
  const jpeg = header[0] === 255 && header[1] === 216 && header[2] === 255;
  const webp =
    String.fromCharCode(...header.slice(0, 4)) === "RIFF" &&
    String.fromCharCode(...header.slice(8, 12)) === "WEBP";
  if (
    !(file.type === "image/png"
      ? png
      : file.type === "image/jpeg"
        ? jpeg
        : webp)
  )
    throw new PluginIconError("invalid");
  const url = URL.createObjectURL(file);
  try {
    const image = new Image();
    image.src = url;
    await image.decode();
    if (
      !image.naturalWidth ||
      !image.naturalHeight ||
      image.naturalWidth * image.naturalHeight > 16_000_000
    )
      throw new PluginIconError("invalid");
    const canvas = document.createElement("canvas");
    canvas.width = ICON_SIZE;
    canvas.height = ICON_SIZE;
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new PluginIconError("invalid");
    const scale = Math.min(
      ICON_SIZE / image.naturalWidth,
      ICON_SIZE / image.naturalHeight,
    );
    const width = image.naturalWidth * scale;
    const height = image.naturalHeight * scale;
    ctx.drawImage(
      image,
      (ICON_SIZE - width) / 2,
      (ICON_SIZE - height) / 2,
      width,
      height,
    );
    const data = canvas.toDataURL("image/png");
    if (!safePluginIcon(data)) throw new PluginIconError("invalid");
    return data;
  } catch (error) {
    if (error instanceof PluginIconError) throw error;
    throw new PluginIconError("invalid");
  } finally {
    URL.revokeObjectURL(url);
  }
}
