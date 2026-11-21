"use client";

import { useAgentsApiEnabled } from "@/core/agents";
import { useAuth } from "@/core/auth/AuthProvider";
import type { NavGateContext } from "@/core/settings/nav-layout";
import { isStaticWebsiteOnly } from "@/core/static-mode";

/**
 * Builds the availability context the sidebar and the customization dialog
 * pass to every registry entry.
 *
 * The context carries only the inputs that exist today: the signed-in user,
 * static mode, and the custom-agent API switch. `useAgentsApiEnabled` owns its
 * own request and last-known cache, so this hook adds no second `/api/features`
 * query. A future switchable entry adds its boolean here next to the hook that
 * owns the feature, and declares the matching gate in `nav-registry.ts`.
 */
export function useNavGateContext(): NavGateContext {
  const { user } = useAuth();
  const { enabled: agentsEnabled } = useAgentsApiEnabled();
  return {
    user,
    staticMode: isStaticWebsiteOnly(),
    agentsEnabled,
  };
}
