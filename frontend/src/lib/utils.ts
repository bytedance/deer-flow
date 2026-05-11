import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** Shared class for external links (underline by default). */
export const externalLinkClass =
  "text-primary underline underline-offset-2 hover:no-underline";
/** Link style without underline by default (e.g. for streaming/loading). */
export const externalLinkClassNoUnderline = "text-primary hover:underline";
