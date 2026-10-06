/**
 * Wire contracts for the admin RAG functional-model configuration
 * (spec 2026-09-10 rag functional-model config §5).
 *
 * Mirrors the backend `RagConfigFile`: every field is optional, `None`/absent means "not
 * declared here", and secrets arrive masked (or empty when the environment backs them).
 */

/** Video-ingestion model choices the settings UI may override. */
export interface RagVideoValues {
  asr_provider?: "funasr" | "whisper" | "openai-audio" | "dashscope" | null;
  asr_model?: string | null;
}

/** One effective RAG configuration object (the PUT body, and the GET's `config`). */
export interface RagConfigValues {
  qdrant_url?: string | null;
  embedding_model?: string | null;
  embedding_api_key?: string | null;
  rerank_model?: string | null;
  rerank_api_key?: string | null;
  vlm_model?: string | null;
  extract_model?: string | null;
  judge_model?: string | null;
  /**
   * The RAG-wide default (spec 2026-09-23 D2): the model every RAG role falls back to when it
   * declares none of its own. A plain `models:` entry name — the backend resolves what to do
   * with it, so this row asks for no endpoint and no key.
   */
  default_model?: string | null;
  /**
   * The two roles that had no field at all (spec 2026-09-26 D2), shaped exactly like the
   * other model references: an entry name the backend resolves, so the rows ask for no
   * endpoint and no key.
   */
  wiki_model?: string | null;
  synthesis_model?: string | null;
  /**
   * Follow-chat thinking toggles (spec 2026-10-03 leg-thinking-follow-chat D1=甲): one
   * boolean per functional role; a checked leg sends "thinking on" exactly like chat does.
   */
  extract_thinking?: boolean | null;
  wiki_thinking?: boolean | null;
  judge_thinking?: boolean | null;
  synthesis_thinking?: boolean | null;
  vlm_thinking?: boolean | null;
  mineru_api_token?: string | null;
  /**
   * Provider dimension (spec 2026-09-14 §4.1). Ids mirror the backend's curated
   * allowlist: a value outside it is rejected by the server, not silently accepted.
   */
  embedding_provider?:
    | "dashscope"
    | "volcengine-ark"
    | "openai-compatible"
    | null;
  embedding_base_url?: string | null;
  embedding_dimension?: number | null;
  embedding_sparse_source?: "provider" | "external" | "bm25" | null;
  sparse_provider?: "tei-sparse" | null;
  sparse_base_url?: string | null;
  sparse_model?: string | null;
  sparse_api_key?: string | null;
  rerank_provider?: "dashscope" | "generic-rerank" | "tei-rerank" | null;
  rerank_base_url?: string | null;
  parse_provider?: "mineru-cloud" | "mineru-local" | null;
  parse_base_url?: string | null;
  parse_tier?: "flash" | "basic" | "standard" | "advanced" | null;
  parse_language?:
    | "ch"
    | "ch_server"
    | "en"
    | "japan"
    | "korean"
    | "chinese_cht"
    | "ta"
    | "te"
    | "ka"
    | "el"
    | "th"
    | "latin"
    | "arabic"
    | "cyrillic"
    | "east_slavic"
    | "devanagari"
    | null;
  parse_model_version?: "pipeline" | "vlm" | null;
  asr_base_url?: string | null;
  asr_api_key?: string | null;
  video?: RagVideoValues | null;
}

/**
 * Where a value comes from. Non-secret fields report `ui` (declared in
 * `rag_config.json`) or `config_file`; secret fields report `ui`, `env` (no stored
 * value but the backing variable is set) or `unset`. Only existence is reported for
 * secrets — never a value.
 */
export type RagConfigSource = "ui" | "config_file" | "env" | "unset";

/**
 * One embedding provider's declared capability (spec 2026-09-16 §3 D1). Read-only metadata
 * from the server's curated allowlist: `emits_sparse` says whether that provider can supply
 * the sparse half itself, and the two endpoint keys say whether the vendor fixes the address
 * (spec 2026-09-17 §3 D1) — so the address row is locked by *capability*, not by provider name.
 * Absent entirely on a response from a server that predates the field, which is why the view
 * treats "unknown" and "cannot" as different answers.
 */
export interface RagEmbeddingProviderCapability {
  provider_id: string;
  emits_sparse: boolean;
  /** True when the vendor fixes this provider's endpoint, so the address row is read-only. */
  has_fixed_endpoint: boolean;
  /** The vendor's own endpoint; the address row shows it when the deployment stored none. */
  default_endpoint: string | null;
}

/**
 * One rerank provider's declared capability (spec 2026-09-17 alignment §3 D3). Same address rule
 * as the embedding block, deliberately a different shape: the rerank leg has no sparse half, so
 * there is no `emits_sparse` here. Absent entirely on a response from a server that predates the
 * field, which the rerank row reads exactly like the embedding row does: unknown ≠ cannot.
 */
export interface RagRerankProviderCapability {
  provider_id: string;
  /** True when the vendor fixes this provider's endpoint, so the address row is read-only. */
  has_fixed_endpoint: boolean;
  /** The vendor's own endpoint; the address row shows it when the deployment stored none. */
  default_endpoint: string | null;
}

/**
 * One ASR provider's declared capability (spec 2026-09-28 §3). Narrower than the two retrieval
 * blocks on purpose: the ASR row reads only the placeholder source, because the lock the others'
 * `has_fixed_endpoint` used to drive was retired by the 2026-09-25 endpoint unlock. Absent
 * entirely on a response from a server that predates the field — the row then falls back to the
 * shared example placeholder.
 */
export interface RagAsrProviderCapability {
  provider_id: string;
  /** The vendor's own endpoint, shown greyed out while the address field is empty. */
  default_endpoint: string | null;
}

/**
 * GET/PUT response: the effective values plus the flattened per-field origin map.
 *
 * `warning` is the save-time probe's verdict (spec 2026-09-17 save-time probe §3 D3): `null` when
 * the configuration was verified, and otherwise why it could not be — the write still went
 * through, because an endpoint that is down now may be up later. It is declared non-optional
 * because it is always present on this contract; a response that predates it reads as `undefined`,
 * which the view treats exactly like `null` (nothing to say).
 */
export interface RagConfigView {
  config: RagConfigValues;
  sources: Record<string, RagConfigSource>;
  embedding_providers?: RagEmbeddingProviderCapability[];
  rerank_providers?: RagRerankProviderCapability[];
  asr_providers?: RagAsrProviderCapability[];
  warning: string | null;
  /**
   * Where the width migration stands (spec 2026-09-26 D5-7). A save that changes the width
   * returns it `running` while `config.embedding_dimension` still holds the *old* value: the
   * switch is an atomic replace inside the background rebuild, so the row must read
   * `target_dimension` for what is coming and `config` for what is in force.
   */
  migration?: RagMigrationStatus | null;
}

/** The width migration's verdict (spec 2026-09-26 D5-7). */
export interface RagMigrationStatus {
  state: "running" | "succeeded" | "failed";
  target_dimension: number;
  detail: string | null;
  progress: Record<string, number> | null;
}

/** PUT body: the whole object, standing in for the new file content. */
export type RagConfigInput = RagConfigValues;

/**
 * Body of the model-level capability probe (spec 2026-09-16 §3 D3): a *candidate* configuration,
 * not a saved one. `embedding_api_key` may be the masking sentinel, which the server reads as
 * "use the stored or environment key" — the admin never has to retype it.
 */
export interface RagSparseProbeRequest {
  embedding_provider: string;
  embedding_model: string;
  embedding_base_url?: string | null;
  embedding_api_key?: string | null;
}

/**
 * The probe's verdict: `unsupported` only when the call succeeded and the sparse half came back
 * empty. Every other failure — unreachable, refused, timed out — is `unverifiable`, which the UI
 * must not read as a refusal (spec §3 D2/D3).
 */
export interface RagSparseProbeResponse {
  status: "supported" | "unsupported" | "unverifiable";
  detail: string;
}

/**
 * Body of the *sparse service* connectivity probe (connectivity spec §3 D1): a candidate service,
 * not a saved one. `sparse_api_key` may be the masking sentinel, which the server reads as "use the
 * stored or environment key".
 */
export interface RagSparseServiceProbeRequest {
  sparse_provider: string;
  sparse_base_url?: string | null;
  sparse_api_key?: string | null;
}

/**
 * Whether the service answered, and whether it answered with anything: `empty` means it is up and
 * shaped right but returned no terms for the probe text — reachable-but-useless, which is a
 * different problem from unreachable (connectivity spec §3 D2).
 */
export interface RagSparseServiceProbeResponse {
  status: "ok" | "empty" | "unreachable";
  detail: string;
}

/**
 * Body of the dimension probe (spec 2026-09-26 §3): a candidate embedding model whose accepted
 * widths are in question. Same read-only contract as its siblings.
 */
export interface RagDimensionProbeRequest {
  embedding_provider: string;
  embedding_model: string;
  embedding_base_url?: string | null;
  embedding_api_key?: string | null;
}

/**
 * Which widths the model accepts. `values` is `[]` for a tiered model that passed nothing (the
 * caller shows the fallback copy instead of an empty list); `candidates` is the backend's own
 * table, so the frontend keeps no second copy of it.
 */
export interface RagDimensionProbeResponse {
  status: "ok" | "unreachable";
  type: "tiered" | "range" | "fixed" | null;
  native: number | null;
  values: number[];
  candidates: number[];
  detail: string;
}

/**
 * One leg's candidate coordinates for a single connectivity call (spec §3 连通探针 D5-5).
 * `embedding_dimension` is the width in force — the embedding leg sends it, so one call also
 * proves the width is obtainable.
 */
export interface RagConnectivityProbeRequest {
  leg: "embedding" | "rerank";
  provider: string;
  model?: string | null;
  base_url?: string | null;
  api_key?: string | null;
  embedding_dimension?: number | null;
}

/** A candidate ASR service to reach, before anything is saved (spec 2026-09-28 D7). */
export interface RagAsrProbeRequest {
  asr_provider: string;
  asr_model: string;
  asr_base_url?: string | null;
  /** Omitted (or the masking sentinel) means "use the stored or environment key". */
  asr_api_key?: string | null;
}

/**
 * Whether the service answers with *real* segment timestamps.
 *
 * `no_timestamps` covers both ways of not having any — no segments at all, and segments whose
 * boundaries were fabricated by pro-rating the duration over character counts — because it is
 * the one state allowed to block a save. `refused` is kept apart from `unreachable` for the
 * same reason the connectivity probe keeps them apart: the repair each one points at differs.
 */
export interface RagAsrProbeResponse {
  status: "ok" | "no_timestamps" | "refused" | "unreachable";
  detail: string;
}

/**
 * `dimension_unavailable` is the second reason an embedding leg can be unusable: it answered,
 * but not with the width we asked for.
 */
export interface RagConnectivityProbeResponse {
  status:
    | "ok"
    | "refused"
    | "unreachable"
    | "dimension_unavailable"
    | "half_missing";
  detail: string;
  measured_dimension: number | null;
}
