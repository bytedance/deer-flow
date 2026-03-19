import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** Shared 类 for external links (underline by 默认). */
export const externalLinkClass =
  "text-primary underline underline-offset-2 hover:no-underline";
/** Link style without underline by 默认 (e.g. for streaming/加载中). */
export const externalLinkClassNoUnderline = "text-primary hover:underline";
