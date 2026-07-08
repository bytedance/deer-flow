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


/** Pretty display name for an agent slug, e.g. "cfi-analyst" -> "CFI Analyst". Routing/delete still use the raw slug. */
const _AGENT_ACRONYMS: Record<string, string> = { cfi: "CFI", ci: "CI", cd: "CD", cicd: "CI/CD", dgx: "DGX", msi: "MSI", rag: "RAG", api: "API", db: "DB", id: "ID", ui: "UI", vpn: "VPN", qa: "QA", llm: "LLM" };
export function prettyAgentName(slug: string): string {
  return (slug || "")
    .split("-")
    .map((w) => _AGENT_ACRONYMS[w.toLowerCase()] ?? (w.charAt(0).toUpperCase() + w.slice(1)))
    .join(" ");
}
