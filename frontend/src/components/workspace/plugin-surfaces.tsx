"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { useAuth } from "@/core/auth/AuthProvider";
import type { PluginSurface, SurfaceSlot } from "@/core/extensions/contracts";
import {
  useFrontendExtensions,
  useFrontendServices,
} from "@/core/extensions/hooks";
import {
  activeFrontendExtensions,
  type LoadedContribution,
} from "@/core/extensions/registry";
import {
  bindFrontendServices,
  openConversation,
} from "@/core/extensions/services";
import { mountSurface } from "@/core/extensions/surfaces";
import { useI18n } from "@/core/i18n/hooks";

function Surface({
  entry,
  surface,
  threadId,
}: {
  entry: LoadedContribution;
  surface: PluginSurface;
  threadId?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const router = useRouter();
  const { locale, t } = useI18n();
  const { user } = useAuth();
  const services = useFrontendServices();
  const currentServices = useRef(services);
  currentServices.current = services;
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    if (!ref.current) return;
    const abort = new AbortController();
    const cleanup = mountSurface(
      ref.current,
      surface,
      {
        namespace: entry.namespace,
        locale,
        settings: entry.settings,
        threadId,
        openConversation: (id, signal) =>
          openConversation(id, (path) => router.push(path), signal),
        callBackend: bindFrontendServices(
          currentServices.current,
          entry,
          abort.signal,
        ).callBackend,
      },
      () => setFailed(true),
    );
    return () => {
      abort.abort();
      cleanup();
    };
  }, [entry, surface, locale, threadId, user?.id, router]);
  return (
    <section aria-label={surface.title}>
      {failed && <p role="alert">{t.extensions.viewFailed}</p>}
      <div ref={ref} />
    </section>
  );
}

export function PluginSurfaces({
  slot,
  namespace,
  surfaceId,
  threadId,
}: {
  slot: SurfaceSlot;
  namespace?: string;
  surfaceId?: string;
  threadId?: string;
}) {
  const query = useFrontendExtensions();
  const { user } = useAuth();
  return activeFrontendExtensions(query.data ?? [])
    .filter(
      ({ contribution }) => !namespace || contribution.namespace === namespace,
    )
    .flatMap(({ contribution: entry, extension }) =>
      (extension.surfaces ?? [])
        .filter(
          (surface) =>
            surface.slot === slot && (!surfaceId || surface.id === surfaceId),
        )
        .map((surface) => (
          <Surface
            key={`${user?.id}:${threadId}:${entry.namespace}:${surface.id}`}
            entry={entry}
            surface={surface}
            threadId={threadId}
          />
        )),
    );
}
