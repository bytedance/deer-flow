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
      const url = new URL(value);
      return url.protocol === "https:" && !url.username && !url.password;
    })
    .optional(),
});
export type ExtensionDocumentation = z.infer<typeof documentationSchema>;

export function localizeDocumentation(
  doc: Pick<ExtensionDocumentation, "locales">,
  locale: string,
) {
  const copy =
    doc.locales[locale] ??
    doc.locales["en-US"] ??
    Object.values(doc.locales)[0]!;
  return { ...copy, gettingStarted: copy.usage };
}

export function bundledCopy(name: keyof typeof bundled, locale: string) {
  return localizeDocumentation(bundled[name], locale);
}
