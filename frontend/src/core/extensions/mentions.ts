import type { ExtensionMention, MentionContext } from "./contracts";
import { activeFrontendExtensions, type LoadedContribution } from "./registry";
import {
  bindFrontendServices,
  conversationText,
  latestVisibleAnswer,
} from "./services";

export const MAX_EXTENSION_MENTIONS = 16;
const identifier = /^[a-z][a-z0-9-]{0,63}$/;
const bounded = (value: unknown, limit: number): value is string =>
  typeof value === "string" && !!value.trim() && value.length <= limit;

export function extensionMentionId(ref: ExtensionMention) {
  return JSON.stringify([ref.namespace, ref.provider, ref.id]);
}

/** Draft references and submitted metadata are untrusted labels, never authority. */
export function parseExtensionMention(
  id: string,
  label: string,
): ExtensionMention | null {
  try {
    if (id.length > 2048 || !bounded(label, 120)) return null;
    const parts: unknown = JSON.parse(id);
    if (!Array.isArray(parts) || parts.length !== 3) return null;
    const [namespace, provider, itemId] = parts as unknown[];
    if (
      typeof namespace !== "string" ||
      !/^[a-z][a-z0-9_.-]{0,127}$/.test(namespace) ||
      typeof provider !== "string" ||
      !identifier.test(provider) ||
      !bounded(itemId, 512)
    )
      return null;
    return { namespace, provider, id: itemId, label };
  } catch {
    return null;
  }
}

export async function searchExtensionMentions(
  entries: LoadedContribution[],
  query: string,
  context: Pick<MentionContext, "locale" | "threadId" | "signal">,
): Promise<{
  items: (ExtensionMention & { description?: string })[];
  failed: boolean;
}> {
  context.signal.throwIfAborted();
  const providers = activeFrontendExtensions(entries)
    .flatMap(({ contribution, extension }) =>
      (extension.mentionProviders ?? []).map((provider) => ({
        contribution,
        provider,
      })),
    )
    .slice(0, 16);
  const results = await Promise.all(
    providers.map(async ({ contribution, provider }) => {
      const abort = new AbortController();
      const cancel = () => abort.abort();
      context.signal.addEventListener("abort", cancel, { once: true });
      let timeout: ReturnType<typeof setTimeout> | undefined;
      let onAbort: (() => void) | undefined;
      try {
        const deadline = new Promise<never>((_, reject) => {
          onAbort = () => reject(new Error("Mention search cancelled"));
          abort.signal.addEventListener("abort", onAbort, { once: true });
          timeout = setTimeout(() => abort.abort(), 3000);
        });
        const services = bindFrontendServices(
          {
            conversationText,
            latestVisibleAnswer,
            showMessage: () => undefined,
          },
          contribution,
          abort.signal,
        );
        const candidates = await Promise.race([
          Promise.resolve().then(() => {
            abort.signal.throwIfAborted();
            return provider.search(query.slice(0, 256), {
              ...context,
              namespace: contribution.namespace,
              settings: contribution.settings,
              signal: abort.signal,
              callBackend: async (action, payload) => {
                abort.signal.throwIfAborted();
                const result = await services.callBackend(action, payload);
                abort.signal.throwIfAborted();
                return result;
              },
            });
          }),
          deadline,
        ]);
        if (!Array.isArray(candidates))
          throw new Error("Invalid mention results");
        const seen = new Set<string>();
        const items: (ExtensionMention & { description?: string })[] = [];
        for (const candidate of candidates.slice(0, 50)) {
          if (
            !candidate ||
            !bounded(candidate.id, 512) ||
            !bounded(candidate.label, 120) ||
            seen.has(candidate.id)
          )
            continue;
          seen.add(candidate.id);
          items.push({
            namespace: contribution.namespace,
            provider: provider.id,
            id: candidate.id,
            label: candidate.label,
            description: bounded(candidate.description, 240)
              ? candidate.description
              : provider.label,
          });
        }
        return { items, failed: false };
      } catch {
        return { items: [], failed: true };
      } finally {
        clearTimeout(timeout);
        if (onAbort) abort.signal.removeEventListener("abort", onAbort);
        abort.abort();
        context.signal.removeEventListener("abort", cancel);
      }
    }),
  );
  context.signal.throwIfAborted();
  return {
    items: results.flatMap((result) => result.items),
    failed: results.some((result) => result.failed),
  };
}
