import { z } from "zod";

import bundled from "./bundled-documentation.json" with { type: "json" };

const text = z.string().trim().min(1).max(4000);
const localized = z.object({
  title: text,
  description: text,
  usage: z
    .array(z.object({ title: text, description: text }))
    .min(1)
    .max(12),
  requirements: z.array(text).max(12).optional(),
});
export const documentationSchema = z.object({
  schema_version: z.literal(1),
  id: z.string(),
  locales: z
    .record(z.string(), localized)
    .refine((value) => Object.keys(value).length > 0),
  docs_url: z
    .url()
    .refine((value) => {
      try {
        const url = new URL(value);
        return url.protocol === "https:" && !url.username && !url.password;
      } catch {
        return false;
      }
    })
    .optional(),
});
export type ExtensionDocumentation = z.infer<typeof documentationSchema>;

export function localizeDocumentation(
  doc: Pick<ExtensionDocumentation, "locales">,
  locale: string,
) {
  const entries = Object.entries(doc.locales);
  const target = locale.toLowerCase();
  const match = (tag: string) =>
    entries.find(([key]) => key.toLowerCase() === tag)?.[1] ??
    entries.find(
      ([key]) => key.toLowerCase().split("-")[0] === tag.split("-")[0],
    )?.[1];
  const copy = match(target) ?? match("en-us") ?? entries[0]![1];
  return {
    ...copy,
    gettingStarted: copy.usage,
    requirements: copy.requirements,
  };
}

export function bundledCopy(name: keyof typeof bundled, locale: string) {
  return localizeDocumentation(bundled[name], locale);
}
