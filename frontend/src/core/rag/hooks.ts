import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { toast } from "sonner";

import {
  loadRagConfig,
  loadRagMigrationStatus,
  probeAsrService,
  probeEmbeddingCapability,
  probeEmbeddingDimensions,
  probeLegConnectivity,
  probeSparseService,
  RagConfigRequestError,
  saveRagConfig,
} from "./api";
import type {
  AsrProbeVerdict,
  ConnectivityProbeVerdict,
  DimensionProbeVerdict,
  SparseProbeVerdict,
  SparseServiceProbeVerdict,
} from "./config-form";
import { migrationRefetchInterval } from "./migration-status";
import type {
  RagAsrProbeRequest,
  RagConfigInput,
  RagConnectivityProbeRequest,
  RagDimensionProbeRequest,
  RagSparseProbeRequest,
  RagSparseServiceProbeRequest,
} from "./types";

/**
 * TanStack Query bindings for the admin RAG functional-model view
 * (spec 2026-09-10 rag functional-model config §5).
 *
 * A 403 is a state the view renders (non-admin), not a transient failure, so it is not
 * retried — same rule the models config query uses.
 */

export function useRagConfig({ enabled = true }: { enabled?: boolean } = {}) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["ragConfig"],
    queryFn: () => loadRagConfig(),
    enabled,
    // The form is seeded from this view; a focus refetch must not clobber edits.
    refetchOnWindowFocus: false,
    retry: (count, error) => !(error instanceof RagConfigRequestError) && count < 3,
  });
  return { view: data, isLoading, error };
}

export function useSaveRagConfig() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: RagConfigInput) => saveRagConfig(input),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["ragConfig"] });
      // A save that changed the width started a rebuild: pick its verdict up at once instead
      // of waiting for the next poll tick.
      void queryClient.invalidateQueries({ queryKey: ["ragMigration"] });
    },
    onError: (error: Error) => {
      toast.error(error.message);
    },
  });
}

/**
 * Where the width migration stands (spec 2026-09-26 D5-7): polls only while one runs, so an
 * idle deployment asks once per mount. Its verdict is what the settings view shows next to
 * the save button — the row keeps rendering the width that is *in force* until the switch.
 */
export function useRagMigrationStatus({ enabled = true }: { enabled?: boolean } = {}) {
  const queryClient = useQueryClient();
  // 迁移「落地」的那一刻才需要重读生效配置：成功则宽度真的换了，失败则没换 —— 两种都要让
  // 表单离开「正在迁移到的那个值」。在飞期间不重读（那时文件里仍是旧宽度，读回来反而误导）。
  const ran = useRef(false);
  const query = useQuery({
    queryKey: ["ragMigration"],
    queryFn: () => loadRagMigrationStatus(),
    enabled,
    refetchInterval: (query) => migrationRefetchInterval(query.state.data),
  });
  const state = query.data?.state;
  useEffect(() => {
    if (state === "running") {
      ran.current = true;
      return;
    }
    if (state && ran.current) {
      ran.current = false;
      void queryClient.invalidateQueries({ queryKey: ["ragConfig"] });
    }
  }, [state, queryClient]);
  return query;
}

/** The probe's input: the candidate configuration, plus the key it was taken for. */
export type SparseProbeInput = RagSparseProbeRequest & { key: string };

/**
 * One model-level capability probe (spec 2026-09-16 §3 D3/D4.2).
 *
 * The verdict is returned together with `key`, the values it describes: the view must never apply
 * a conclusion to a form it was not taken for. It deliberately does not invalidate the config
 * query — nothing was written — and failures are left to the caller: a probe that could not
 * answer is a state the row renders (`unverifiable`), not a toast to dismiss.
 */
export function useProbeSparseCapability() {
  return useMutation({
    mutationFn: async ({
      key,
      ...request
    }: SparseProbeInput): Promise<SparseProbeVerdict> => {
      const verdict = await probeEmbeddingCapability(request);
      return { key, status: verdict.status };
    },
  });
}

/** The sparse-service probe's input: the candidate service, plus the key it was taken for. */
export type SparseServiceProbeInput = RagSparseServiceProbeRequest & {
  key: string;
};

/**
 * One connectivity probe against the external sparse service (connectivity spec §3 D1/D4).
 *
 * Same contract as the capability probe: the verdict carries the values it describes, nothing is
 * invalidated (nothing was written), and a failure is a state the row renders rather than a toast —
 * an unreachable service is information, and it never blocks a save.
 */
export function useProbeSparseService() {
  return useMutation({
    mutationFn: async ({
      key,
      ...request
    }: SparseServiceProbeInput): Promise<SparseServiceProbeVerdict> => {
      const verdict = await probeSparseService(request);
      return { key, status: verdict.status };
    },
  });
}

/** The dimension probe's input: the candidate values, plus the key they were taken for. */
export type DimensionProbeInput = RagDimensionProbeRequest & { key: string };

/**
 * One dimension probe (spec 2026-09-26 §3).
 *
 * Same contract as its siblings: the verdict carries the values it describes, nothing is
 * invalidated (nothing was written), and a failure is a state the row renders —「未探明」 is
 * information, and it never blocks a save.
 */
export function useProbeDimensions() {
  return useMutation({
    mutationFn: async ({
      key,
      ...request
    }: DimensionProbeInput): Promise<DimensionProbeVerdict> => {
      const verdict = await probeEmbeddingDimensions(request);
      return { ...verdict, key };
    },
  });
}

/** The ASR probe's input: the candidate service, plus the key it was taken for. */
export type AsrProbeInput = RagAsrProbeRequest & { key: string };

/**
 * One call against an ASR service (spec 2026-09-28 D7). Manual by design, like the two legs'
 * dots: the answer only ever comes from a click, and nothing is invalidated (nothing was
 * written). The verdict carries the values it describes, so editing them drops it.
 */
export function useProbeAsrService() {
  return useMutation({
    mutationFn: async ({
      key,
      ...request
    }: AsrProbeInput): Promise<AsrProbeVerdict> => {
      const verdict = await probeAsrService(request);
      return { ...verdict, key };
    },
  });
}

/** The connectivity probe's input: one leg's candidate coordinates, plus the key. */
export type ConnectivityProbeInput = RagConnectivityProbeRequest & { key: string };

/**
 * One connectivity call per leg (D5-5). Manual by裁: the dot's answer only ever comes from a
 * click, and it lives for the session — the save-time probe's verdict is not fed into it.
 */
export function useProbeConnectivity() {
  return useMutation({
    mutationFn: async ({
      key,
      ...request
    }: ConnectivityProbeInput): Promise<ConnectivityProbeVerdict> => {
      const verdict = await probeLegConnectivity(request);
      return { ...verdict, key };
    },
  });
}
