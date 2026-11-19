import type { Translations } from "@/core/i18n";

import type {
  ConversationAction,
  ConversationActionGroup,
  FrontendContribution,
  FrontendExtension,
} from "./contracts";

/** Evaluate locale-dependent plugin callbacks inside a per-contribution boundary. */
export function resolveConversationActions(
  extension: FrontendExtension,
  contribution: FrontendContribution,
  t: Translations,
  locale: string,
): ConversationActionGroup | undefined {
  try {
    const group = extension.conversationActions?.(t, locale);
    if (group == null) return;
    const { label, icon, actions } = group;
    if (
      typeof label !== "string" ||
      !label.trim() ||
      typeof icon !== "string" ||
      !Array.isArray(actions)
    ) {
      // A misdeclared async factory must not leak a rejected Promise.
      void Promise.resolve(group).catch(() => undefined);
      throw new Error("Invalid conversation action group");
    }
    const ids = new Set<string>();
    const visible: ConversationAction[] = [];
    for (const action of actions) {
      const { id, label, icon, available, execute } = action;
      if (
        typeof id !== "string" ||
        !id.trim() ||
        ids.has(id) ||
        typeof label !== "string" ||
        !label.trim() ||
        typeof icon !== "string" ||
        typeof available !== "function" ||
        typeof execute !== "function"
      )
        throw new Error("Invalid conversation action");
      ids.add(id);
      const enabled = available.call(action, contribution.settings);
      if (typeof enabled !== "boolean") {
        // Reject async availability while observing any eventual rejection.
        void Promise.resolve(enabled).catch(() => undefined);
        throw new Error("Invalid action availability");
      }
      if (enabled)
        visible.push({
          id,
          label,
          icon,
          available: (settings) => available.call(action, settings),
          execute: (context, services) =>
            execute.call(action, context, services),
        });
    }
    // Copy validated values so plugin getters are not evaluated again by React.
    return visible.length ? { label, icon, actions: visible } : undefined;
  } catch (error) {
    console.warn(
      `Plugin conversation actions unavailable: ${contribution.namespace}`,
      error,
    );
    return undefined;
  }
}
