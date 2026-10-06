import { MASKED_RAG_SECRET } from "./api";
import type {
  RagConfigValues,
  RagConfigView,
  RagConfigInput,
  RagConnectivityProbeResponse,
  RagDimensionProbeResponse,
  RagEmbeddingProviderCapability,
  RagVideoValues,
} from "./types";

/**
 * Form mapping for the RAG functional-model view (spec 2026-09-10 §5).
 *
 * The backend PUT replaces the whole API-writable object, so the payload is *not* a
 * patch: whatever it omits is removed from the file and reverts to `config.yaml` (or,
 * for a secret, to the environment). That makes two rules load-bearing:
 *
 * 1. Fields the file already owns are carried forward, so editing one row cannot
 *    silently drop the file's other overrides.
 * 2. An untouched stored secret is re-submitted as the sentinel so the server keeps it;
 *    emptying the input is the explicit "stop overriding, fall back to the environment".
 *
 * Fields the operator owns (source `config_file`) are only submitted once the admin
 * actually overrides them — otherwise saving the form would freeze today's `config.yaml`
 * values into the file and silently outrank every later operator edit.
 */

/** One editable row of the functional-model form. */
export interface RagConfigFormValues {
  qdrant_url: string;
  embedding_model: string;
  embedding_api_key: string;
  rerank_model: string;
  rerank_api_key: string;
  vlm_model: string;
  extract_model: string;
  judge_model: string;
  default_model: string;
  wiki_model: string;
  synthesis_model: string;
  /** Follow-chat thinking toggles (spec 2026-10-03 D1=甲); a checkbox is two-state, so an
   * explicit `false` is how the form says "not this leg" (the file's `null` = undeclared). */
  extract_thinking: boolean;
  wiki_thinking: boolean;
  judge_thinking: boolean;
  synthesis_thinking: boolean;
  vlm_thinking: boolean;
  mineru_api_token: string;
  embedding_provider: "dashscope" | "volcengine-ark" | "openai-compatible";
  embedding_base_url: string;
  /**
   * The library width, as text so "not set" has its own spelling (""), like every other row.
   * It round-trips through the numeric-field class below: the backend stores an int, and a
   * blank means "stop overriding" rather than 0 (spec 2026-09-26 §3 维度字段的往返).
   */
  embedding_dimension: string;
  embedding_sparse_source: "provider" | "external" | "bm25";
  sparse_provider: "tei-sparse" | "";
  sparse_base_url: string;
  sparse_model: string;
  sparse_api_key: string;
  rerank_provider: "dashscope" | "generic-rerank" | "tei-rerank";
  rerank_base_url: string;
  parse_provider: "mineru-cloud" | "mineru-local";
  parse_base_url: string;
  parse_tier: "flash" | "basic" | "standard" | "advanced" | "";
  parse_language:
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
    | "";
  parse_model_version: "pipeline" | "vlm" | "";
  /** The ASR leg's connection info — top level, beside the other legs' (① 乙, 2026-09-29). */
  asr_base_url: string;
  asr_api_key: string;
  video: {
    asr_provider: "funasr" | "whisper" | "openai-audio" | "dashscope";
    asr_model: string;
  };
}

/**
 * The select options for the provider dimension. These mirror the backend's curated
 * allowlist (`deerflow.knowledge.providers`), which is the authority: a value outside it
 * is rejected with a 422 rather than silently accepted, so drift shows up loudly.
 */
export const EMBEDDING_PROVIDER_OPTIONS = [
  "dashscope",
  "volcengine-ark",
  "openai-compatible",
] as const;
export const EMBEDDING_SPARSE_SOURCE_OPTIONS = ["provider", "external", "bm25"] as const;
/** The sparse service's id set: one verified shape (TEI's `/embed_sparse`), spec §4.2. */
export const SPARSE_PROVIDER_OPTIONS = ["", "tei-sparse"] as const;
export const RERANK_PROVIDER_OPTIONS = [
  "dashscope",
  "generic-rerank",
  "tei-rerank",
] as const;
export const PARSE_PROVIDER_OPTIONS = ["mineru-cloud", "mineru-local"] as const;
/**
 * The 4.x service tiers (spec 2026-09-24 §4.3); the empty option means "let the local MinerU
 * service decide". The retired `vlm` / `hybrid` pair has no 4.x equivalent — the backend choice
 * became a service startup flag, so there is nothing to translate it to (D2).
 */
export const PARSE_TIER_OPTIONS = [
  "",
  "flash",
  "basic",
  "standard",
  "advanced",
] as const;
/**
 * The cloud leg's document-language packs (spec 2026-09-29 D1): the backend Literal's full
 * 16-value table. The empty option means "not declared here" — the configured default (`ch`)
 * applies; the local leg has no language knob.
 */
export const PARSE_LANGUAGE_OPTIONS = [
  "",
  "ch",
  "ch_server",
  "en",
  "japan",
  "korean",
  "chinese_cht",
  "ta",
  "te",
  "ka",
  "el",
  "th",
  "latin",
  "arabic",
  "cyrillic",
  "east_slavic",
  "devanagari",
] as const;
/**
 * The cloud leg's model version (spec 2026-09-29 D1); `vlm` is what this deployment has
 * always sent, and the empty option falls back to the configured default.
 */
export const PARSE_MODEL_VERSION_OPTIONS = ["", "pipeline", "vlm"] as const;
/**
 * The ASR leg's providers (spec 2026-09-28 D2「三组四值」): the two engines that run inside
 * this process, then one row per protocol family — the generic OpenAI-audio shape and the
 * vendor's own. The list mirrors the backend allowlist like the others above; the dropdown
 * groups it, and `ASR_LOCAL_ENGINES` is the subset whose rows take neither an address nor a
 * key.
 */
export const ASR_PROVIDER_OPTIONS = [
  "funasr",
  "whisper",
  "openai-audio",
  "dashscope",
] as const;
export const ASR_LOCAL_ENGINES = ["funasr", "whisper"] as const;
/** One ASR provider id, as the row and the switch helper spell it. */
export type AsrProvider = (typeof ASR_PROVIDER_OPTIONS)[number];

const SECRET_FIELDS = [
  "embedding_api_key",
  "rerank_api_key",
  "mineru_api_token",
  "sparse_api_key",
  "asr_api_key",
] as const;

const TEXT_FIELDS = [
  "qdrant_url",
  "embedding_model",
  "rerank_model",
  "vlm_model",
  "extract_model",
  "judge_model",
  "default_model",
  "wiki_model",
  "synthesis_model",
  "embedding_base_url",
  "sparse_base_url",
  "sparse_model",
  "rerank_base_url",
  "parse_base_url",
  "asr_base_url",
] as const;

/**
 * Integer fields. They follow the same carry-forward rule as text, but the wire wants a number:
 * a blank input means "stop overriding" (so a stored value is removed) and a non-numeric input is
 * simply not submitted — the row's own validation owns that copy, never the payload.
 */
const NUMERIC_FIELDS = ["embedding_dimension"] as const;

/** Enum selects: they carry their own union type, so they are handled apart from text. */
const SELECT_FIELDS = [
  "embedding_provider",
  "embedding_sparse_source",
  "sparse_provider",
  "rerank_provider",
  "parse_provider",
  "parse_tier",
  "parse_language",
  "parse_model_version",
] as const;

/** The follow-chat thinking toggles: plain booleans, unlike the text/select fields. */
const THINKING_FIELDS = [
  "extract_thinking",
  "wiki_thinking",
  "judge_thinking",
  "synthesis_thinking",
  "vlm_thinking",
] as const;

const VIDEO_SOURCES: Record<string, string> = {
  asr_provider: "video.asr_provider",
  asr_model: "video.asr_model",
};

function asText(value: unknown): string {
  return typeof value === "string" ? value : "";
}

/** Narrow a wire value onto one of a select's options, falling back when it is absent or unknown. */
function asEnum<T extends string>(value: unknown, options: readonly T[], fallback: T): T {
  return typeof value === "string" && (options as readonly string[]).includes(value) ? (value as T) : fallback;
}

/** Effective view → form values; a stored secret stays masked so the input shows it as set. */
export function formValuesFromConfig(view: RagConfigView): RagConfigFormValues {
  const config = view.config ?? {};
  const video: RagVideoValues = config.video ?? {};
  return {
    qdrant_url: asText(config.qdrant_url),
    embedding_model: asText(config.embedding_model),
    embedding_api_key: asText(config.embedding_api_key),
    rerank_model: asText(config.rerank_model),
    rerank_api_key: asText(config.rerank_api_key),
    vlm_model: asText(config.vlm_model),
    extract_model: asText(config.extract_model),
    judge_model: asText(config.judge_model),
    default_model: asText(config.default_model),
    wiki_model: asText(config.wiki_model),
    synthesis_model: asText(config.synthesis_model),
    extract_thinking: Boolean(config.extract_thinking),
    wiki_thinking: Boolean(config.wiki_thinking),
    judge_thinking: Boolean(config.judge_thinking),
    synthesis_thinking: Boolean(config.synthesis_thinking),
    vlm_thinking: Boolean(config.vlm_thinking),
    mineru_api_token: asText(config.mineru_api_token),
    embedding_provider: asEnum(config.embedding_provider, EMBEDDING_PROVIDER_OPTIONS, "dashscope"),
    embedding_base_url: asText(config.embedding_base_url),
    embedding_dimension: config.embedding_dimension == null ? "" : String(config.embedding_dimension),
    embedding_sparse_source: asEnum(config.embedding_sparse_source, EMBEDDING_SPARSE_SOURCE_OPTIONS, "provider"),
    sparse_provider: asEnum(config.sparse_provider, SPARSE_PROVIDER_OPTIONS, ""),
    sparse_base_url: asText(config.sparse_base_url),
    sparse_model: asText(config.sparse_model),
    sparse_api_key: asText(config.sparse_api_key),
    rerank_provider: asEnum(config.rerank_provider, RERANK_PROVIDER_OPTIONS, "dashscope"),
    rerank_base_url: asText(config.rerank_base_url),
    parse_provider: asEnum(config.parse_provider, PARSE_PROVIDER_OPTIONS, "mineru-cloud"),
    parse_base_url: asText(config.parse_base_url),
    parse_tier: asEnum(config.parse_tier, PARSE_TIER_OPTIONS, ""),
    parse_language: asEnum(config.parse_language, PARSE_LANGUAGE_OPTIONS, ""),
    parse_model_version: asEnum(config.parse_model_version, PARSE_MODEL_VERSION_OPTIONS, ""),
    asr_base_url: asText(config.asr_base_url),
    asr_api_key: asText(config.asr_api_key),
    video: {
      asr_provider: asEnum(video.asr_provider, ASR_PROVIDER_OPTIONS, "funasr"),
      asr_model: asText(video.asr_model),
    },
  };
}

function owned(view: RagConfigView, key: string): boolean {
  return view.sources?.[key] === "ui";
}

function loaded(view: RagConfigView, key: keyof RagConfigValues): string {
  return asText(view.config?.[key]);
}

/** The same "what is in force today" read for the integer rows, which store a number. */
function loadedNumber(view: RagConfigView, key: keyof RagConfigValues): string {
  const value = view.config?.[key];
  return typeof value === "number" ? String(value) : "";
}

/** Write one field of the payload; the caller has already narrowed the key and value. */
function writeField(input: RagConfigInput, key: string, value: unknown): void {
  (input as Record<string, unknown>)[key] = value;
}

/**
 * Build the PUT body: the file's current overrides carried forward, plus this edit.
 *
 * Returns `{}` when the admin changed nothing and the file owns nothing — the caller
 * must treat an empty payload as "nothing to save" (sending it would clear the file).
 */
export function buildRagConfigInput(
  values: RagConfigFormValues,
  view: RagConfigView,
): RagConfigInput {
  const input: RagConfigInput = {};

  for (const key of TEXT_FIELDS) {
    const next = values[key].trim();
    const previous = loaded(view, key);
    if (next === previous) {
      if (next !== "" && owned(view, key)) {
        input[key] = next; // carry the file's own override forward
      }
      continue;
    }
    // An override this edit introduces (or, when the file owns the field, an explicit clear).
    if (next !== "" || owned(view, key)) {
      input[key] = next;
    }
  }

  for (const key of NUMERIC_FIELDS) {
    const raw = values[key].trim();
    const previous = loadedNumber(view, key);
    if (raw === previous) {
      if (raw !== "" && owned(view, key)) {
        input[key] = Number(raw); // carry the file's own override forward
      }
      continue;
    }
    if (raw === "") {
      if (owned(view, key)) input[key] = null; // stop overriding: fall back to config.yaml
      continue;
    }
    const parsed = Number(raw);
    if (!Number.isInteger(parsed) || parsed <= 0) continue; // the row's validation owns that copy
    input[key] = parsed;
  }

  for (const key of SECRET_FIELDS) {
    const next = values[key].trim();
    if (next === MASKED_RAG_SECRET) {
      if (owned(view, key)) {
        input[key] = MASKED_RAG_SECRET; // keep the stored key
      }
      continue;
    }
    if (next === "") {
      if (owned(view, key)) {
        input[key] = ""; // stop overriding: fall back to the environment
      }
      continue;
    }
    input[key] = next;
  }

  // Enum selects follow the same carry-forward rule. They write through a widened view
  // because their option unions differ per field, which TS cannot prove from a key union.
  for (const key of SELECT_FIELDS) {
    const next = values[key];
    const previous = asText(view.config?.[key]);
    if (next === previous) {
      if (next !== "" && owned(view, key)) writeField(input, key, next); // carry the file's own override
      continue;
    }
    // A cleared select must be *said* as `null`: `""` fails the Literal on the PUT body (422),
    // so an empty option used to leave the override unremovable (spec 2026-09-29 §6.2 末条).
    if (next !== "" || owned(view, key)) writeField(input, key, next === "" ? null : next);
  }

  for (const key of THINKING_FIELDS) {
    const next = values[key];
    const previous = Boolean(view.config?.[key]);
    if (next === previous) {
      if (owned(view, key)) writeField(input, key, next); // carry the file's own override
      continue;
    }
    writeField(input, key, next);
  }

  const video: RagVideoValues = {};
  const loadedVideo: RagVideoValues = view.config?.video ?? {};

  // The two free-text fields share one rule...
  for (const key of ["asr_model"] as const) {
    const source = VIDEO_SOURCES[key]!;
    const previous = asText(loadedVideo[key]);
    const next = values.video[key].trim();
    if (next === previous) {
      if (next !== "" && owned(view, source)) {
        video[key] = next;
      }
      continue;
    }
    if (next !== "" || owned(view, source)) {
      video[key] = next;
    }
  }

  // ...while the provider is an enum select, so it keeps its own union type. Judged against
  // the same option list the row renders: the old two-value narrowing silently rewrote a
  // service tier back to `funasr`, so the new tiers could never be saved (spec 2026-09-28 D2).
  const provider = asEnum(values.video.asr_provider, ASR_PROVIDER_OPTIONS, "funasr");
  const loadedProvider = asEnum(loadedVideo.asr_provider, ASR_PROVIDER_OPTIONS, "funasr");
  if (provider !== loadedProvider || owned(view, VIDEO_SOURCES.asr_provider!)) {
    video.asr_provider = provider;
  }
  if (Object.keys(video).length > 0) {
    input.video = video;
  }

  return input;
}

/**
 * Whether this edit invalidates the vectors of every knowledge base already indexed — which
 * means re-indexing, not just a settings change. It covers the whole provider dimension
 * (spec 2026-09-14 §5), not only the model name: switching provider, endpoint or sparse
 * source changes the vectors too, so warning on the model alone would miss most switches.
 */
export function isEmbeddingChange(
  values: RagConfigFormValues,
  view: RagConfigView,
): boolean {
  const seeded = formValuesFromConfig(view);
  return (
    values.embedding_model.trim() !== seeded.embedding_model.trim() ||
    values.embedding_provider !== seeded.embedding_provider ||
    values.embedding_base_url.trim() !== seeded.embedding_base_url.trim() ||
    values.embedding_dimension.trim() !== seeded.embedding_dimension.trim() ||
    values.embedding_sparse_source !== seeded.embedding_sparse_source
  );
}

/**
 * The two ASR engines' candidate menus, in recommendation order (spec 2026-09-27 §7.1/§7.3).
 * The first row of each is also that engine's default: a provider switch has nothing else to
 * fall back to, so one table serves both the dropdown and the fallback.
 */
export const ASR_MODEL_MENU = {
  funasr: ["paraformer-zh", "paraformer-en"],
  // `small` leads because it is the tier most people should use — the fallback is this row.
  whisper: ["small", "tiny", "base", "medium", "large-v3", "large-v3-turbo"],
} as const;

/**
 * Every name `openai-whisper` accepts, aliases and `.en` variants included. The judgement set
 * is deliberately wider than the menu (spec 2026-09-27 §2 D2): `turbo` and `large` are legal
 * whisper names the menu does not offer, and a menu-sized judgement would leave them in place
 * when the admin switches to funasr — where they fail only at the next ingest.
 */
const WHISPER_MODEL_NAMES: ReadonlySet<string> = new Set([
  "tiny.en",
  "tiny",
  "base.en",
  "base",
  "small.en",
  "small",
  "medium.en",
  "medium",
  "large-v1",
  "large-v2",
  "large-v3",
  "large",
  "turbo",
  "large-v3-turbo",
]);

/**
 * The model value a provider switch leaves behind (spec 2026-09-27 §2 D2). Only the whisper
 * side can judge "illegal": funasr is an open set — any ModelScope repo id, or a local
 * directory — so its menu must never double as a filter, and everything that is not a whisper
 * name is carried over untouched.
 */
export function asrModelForProviderSwitch(next: AsrProvider, value: string): string {
  const name = value.trim();
  // The service tiers have no candidate row to fall back to — the name is the service's own,
  // and only the probe can say whether it is one it knows. So the value is carried over, and
  // the admin is the one who changes it.
  if (next === "openai-audio" || next === "dashscope") {
    return value;
  }
  if (next === "funasr") {
    return WHISPER_MODEL_NAMES.has(name) ? ASR_MODEL_MENU.funasr[0] : value;
  }
  return WHISPER_MODEL_NAMES.has(name) ? value : ASR_MODEL_MENU.whisper[0];
}

/** The width every deployment starts at; a blank declaration keeps it (spec 2026-09-26 D1 乙). */
export const DEFAULT_EMBEDDING_DIMENSION = 1024;

function effectiveDimension(raw: string | number | null | undefined): number {
  const text = typeof raw === "number" ? String(raw) : (raw ?? "").trim();
  const parsed = Number.parseInt(text, 10);
  return Number.isFinite(parsed) && parsed > 0
    ? parsed
    : DEFAULT_EMBEDDING_DIMENSION;
}

/**
 * Whether this save moves the vector library's *width* — the one edit that cannot take effect
 * on its own: the server rebuilds every library into a new generation first and switches only
 * when that is complete (spec 2026-09-26 D5-7), so the view confirms it before saving.
 *
 * Compared as effective widths, so typing `1024` over a blank field is not a change (the same
 * rule the server applies), while clearing a declaration *is* one.
 */
export function changesEmbeddingDimension(
  values: RagConfigFormValues,
  view: RagConfigView,
): boolean {
  return (
    effectiveDimension(values.embedding_dimension) !==
    effectiveDimension(view.config.embedding_dimension)
  );
}

/**
 * Whether the form asks the selected embedding provider for a sparse half it cannot produce
 * (spec 2026-09-16 §3 D2) — the one combination the pipeline refuses to build, so the admin
 * should hear about it here rather than on the next ingest.
 *
 * Judged from the **form's** provider, not the seeded one: switching the picker has to warn
 * immediately, before anything is saved. `providers` is the server's capability list; missing
 * data — an older response, or a provider the server did not list — answers `false`, because
 * an unknown is not a defect and warning about what we cannot know is worse than silence.
 *
 * `probe` adds the model-level answer (see `resolveSparseCapability`), so a model the platform
 * itself refused is caught the same way as a dense-only dialect.
 */
export function isSparseSourceUnsupported(
  values: RagConfigFormValues,
  providers: readonly RagEmbeddingProviderCapability[] | undefined,
  probe?: SparseProbeVerdict | null,
): boolean {
  if (values.embedding_sparse_source !== "provider") return false;
  return resolveSparseCapability(values, providers, probe) === "unsupported";
}

/**
 * Whether the form asks for a separate sparse service but never chose one.
 *
 * The runtime refuses exactly this pair (`external` requires a concrete `sparse_provider`), and the
 * empty id is what a fresh external configuration seeds — Radix needs a non-empty option value, so
 * "not chosen" travels as `""`. Refusing it here rather than at the next save is the same rule the
 * dense-only check follows: a combination that is *known* to be rejected should not be storable.
 */
export function isSparseServiceUnconfigured(
  values: RagConfigFormValues,
): boolean {
  return (
    values.embedding_sparse_source === "external" &&
    values.sparse_provider === ""
  );
}

/**
 * What a probe learned about one candidate configuration (spec 2026-09-16 §3 D3), carrying the
 * values it was taken for. The key is not decoration: a verdict without it would be applied to
 * whatever the form says later, which is exactly how a just-refused model slips through.
 */
export interface SparseProbeVerdict {
  key: string;
  status: "supported" | "unsupported" | "unverifiable";
}

/**
 * The identity a probe verdict belongs to (spec §3 D4.2): the three values that decide what the
 * call would actually ask. Everything else on the form is a different leg or a different
 * question — the sparse source *is* the question being asked, so it is deliberately not part of
 * the key.
 */
export function sparseProbeKey(values: RagConfigFormValues): string {
  return [
    values.embedding_provider,
    values.embedding_model.trim(),
    values.embedding_base_url.trim(),
  ].join("|");
}

/** The three-state answer the UI renders (spec §3 D2). */
export type SparseCapability = "supported" | "unsupported" | "unknown";

/**
 * Combine the two sources that know something about the sparse half (spec §3 D2).
 *
 * The allowlist answers the *dialect* question for free — a provider that cannot emit sparse at
 * all needs no call. Whether a particular model on a capable provider does is only knowable by
 * asking it, so that answer is taken from the probe, and **only** when the probe was run for
 * exactly these values. Anything unproven is `unknown`, which the caller must treat as no worse
 * than today (see `isSparseProviderOptionDisabled`).
 */
export function resolveSparseCapability(
  values: RagConfigFormValues,
  providers: readonly RagEmbeddingProviderCapability[] | undefined,
  probe: SparseProbeVerdict | null | undefined,
): SparseCapability {
  const capability = providers?.find(
    (provider) => provider.provider_id === values.embedding_provider,
  );
  if (capability?.emits_sparse === false) return "unsupported";
  if (probe?.key !== sparseProbeKey(values)) return "unknown";
  if (probe.status === "supported") return "supported";
  if (probe.status === "unsupported") return "unsupported";
  // "Could not check" is not "cannot do it".
  return "unknown";
}

/**
 * Whether the 「跟随向量模型」 option has to be picked-but-unselectable (spec §3 D4.1).
 *
 * Only a *known* refusal disables it: treating `unknown` as a refusal would lock a working
 * configuration out the moment the platform is unreachable, which is worse than the silence
 * this whole line set out to fix.
 */
export function isSparseProviderOptionDisabled(
  capability: SparseCapability,
): boolean {
  return capability === "unsupported";
}

/** Grey placeholder for an endpoint row with no vendor default (never a real value). */
export const ENDPOINT_PLACEHOLDER_FALLBACK = "https://api.example.com/v1";

/**
 * The endpoint rows are always editable (spec 2026-09-25 rag-endpoint-unlock): the same vendor
 * may serve different addresses (a DashScope workspace-scoped endpoint is the standing example),
 * so there is no lock and no restore-to-default. The capability block's `default_endpoint` is
 * only the grey placeholder hint — never a value, never a runtime fallback.
 */
export function endpointPlaceholderFor(
  providers:
    | readonly { provider_id: string; default_endpoint: string | null }[]
    | undefined,
  providerId: string,
): string {
  return (
    providers?.find((entry) => entry.provider_id === providerId)
      ?.default_endpoint ?? ENDPOINT_PLACEHOLDER_FALLBACK
  );
}

/** Radix Select rejects an empty item value, so "not configured" gets its own token. */
export const MODEL_REFERENCE_NONE = "__none__";

/** What a connectivity probe learned about the external sparse service (connectivity spec §3 D2). */
export interface SparseServiceProbeVerdict {
  key: string;
  status: "ok" | "empty" | "unreachable";
}

/**
 * Whether the form describes a service there is any point in calling (connectivity spec §3 D4).
 *
 * Only the `external` source reaches out at all — the provider's own sparse half is asked about by
 * the capability probe, and BM25 never leaves the machine. An address is required because the
 * runtime refuses to build without one, so a probe would only report a certainty.
 */
export function shouldProbeSparseService(values: RagConfigFormValues): boolean {
  return (
    values.embedding_sparse_source === "external" &&
    values.sparse_provider !== "" &&
    values.sparse_base_url.trim() !== ""
  );
}

/**
 * The identity a service verdict belongs to (connectivity spec §3 D4): the address it was taken
 * for, plus whether a key existed at the time — adding one can turn a 401 into an answer, so it is
 * a different question.
 */
export function sparseServiceProbeKey(
  values: RagConfigFormValues,
  hasKey: boolean,
): string {
  return [
    values.sparse_provider,
    values.sparse_base_url.trim(),
    hasKey ? "key" : "nokey",
  ].join("|");
}

/** The ASR probe's verdict (spec 2026-09-28 D7), tagged with the values it describes. */
export interface AsrProbeVerdict {
  key: string;
  status: "ok" | "no_timestamps" | "refused" | "unreachable";
  detail: string;
}

/**
 * Whether this row has a service to call at all (D7): only the two protocol tiers reach out —
 * the in-process engines have no endpoint, and they already degrade to `asr_failed` when their
 * models are missing, so a probe would only be a second way to learn the same thing.
 */
export function shouldProbeAsr(values: RagConfigFormValues): boolean {
  return (ASR_PROVIDER_OPTIONS as readonly string[]).includes(
    values.video.asr_provider,
  )
    ? !(ASR_LOCAL_ENGINES as readonly string[]).includes(
        values.video.asr_provider,
      )
    : false;
}

/** The ASR probe's identity: the four values that decide what the call would ask. */
export function asrProbeKey(
  values: RagConfigFormValues,
  hasKey: boolean,
): string {
  return [
    values.video.asr_provider,
    values.video.asr_model.trim(),
    values.asr_base_url.trim(),
    hasKey ? "key" : "nokey",
  ].join("|");
}

/**
 * Whether a probe verdict may still speak for the form: it only counts for the values it was
 * taken for — editing the provider, the model or the address is asking a different question.
 */
export function asrProbeVerdictFor(
  values: RagConfigFormValues,
  hasKey: boolean,
  verdict: AsrProbeVerdict | null,
): AsrProbeVerdict | null {
  return verdict?.key === asrProbeKey(values, hasKey) ? verdict : null;
}

/**
 * The one probe state that blocks a save (D7): a service that cannot give segment-level
 * timestamps makes its own row pointless — the cards would be assembled from rows that cannot
 * be projected onto them. Everything else the probe can report is information: an endpoint that
 * is down now may be up in a minute, and refusing the write would close the admin's exit.
 */
export function asrProbeBlocksSave(verdict: AsrProbeVerdict | null): boolean {
  return verdict?.status === "no_timestamps";
}

/**
 * The dimension probe's verdict, tagged with the values it describes (spec 2026-09-26 §3): the
 * view must never apply a conclusion to a form it was not taken for.
 */
export type DimensionProbeVerdict = RagDimensionProbeResponse & { key: string };

/** The values the dimension answer is about — the width itself is *not* among them. */
export function dimensionProbeKey(values: RagConfigFormValues): string {
  return [
    values.embedding_provider,
    values.embedding_model.trim(),
    values.embedding_base_url.trim(),
  ].join("|");
}

/** The connectivity probe's verdict (D5-5); same "verdict carries its key" contract. */
export type ConnectivityProbeVerdict = RagConnectivityProbeResponse & { key: string };

/**
 * The coordinates one leg's dot is about. The embedding leg includes the width in force: asking
 * for 1536 after choosing 1024 is a different question, so the old answer must be dropped.
 */
export function connectivityProbeKey(
  leg: "embedding" | "rerank",
  values: RagConfigFormValues,
  hasKey: boolean,
): string {
  const coordinates =
    leg === "embedding"
      ? [
          values.embedding_provider,
          values.embedding_model.trim(),
          values.embedding_base_url.trim(),
          values.embedding_dimension.trim(),
        ]
      : [values.rerank_provider, values.rerank_model.trim(), values.rerank_base_url.trim()];
  return [leg, ...coordinates, hasKey ? "key" : "nokey"].join("|");
}

/** The verdict for these values, or `null` when it was taken for other ones. */
export function sparseServiceVerdictFor(
  values: RagConfigFormValues,
  hasKey: boolean,
  probe: SparseServiceProbeVerdict | null | undefined,
): SparseServiceProbeVerdict | null {
  if (!probe) return null;
  return probe.key === sparseServiceProbeKey(values, hasKey) ? probe : null;
}

export interface ModelReferenceOption {
  value: string;
  label: string;
}

/**
 * Options for a picker whose value is a `models:` entry name (graph extraction, eval
 * judge): the configured chat models, with an explicit "not configured" entry that means
 * "let the backend pick". A stored value whose model was deleted stays listed (labelled
 * as itself) so opening the form cannot silently clear it.
 */
export function modelReferenceOptions(
  models: readonly { name: string; display_name?: string | null }[],
  current: string,
  noneLabel: string,
): ModelReferenceOption[] {
  const options: ModelReferenceOption[] = [
    { value: MODEL_REFERENCE_NONE, label: noneLabel },
  ];
  for (const model of models) {
    const display = model.display_name?.trim();
    const hasDisplay = display !== undefined && display.length > 0;
    options.push({ value: model.name, label: hasDisplay ? display : model.name });
  }
  if (current && !models.some((model) => model.name === current)) {
    options.push({ value: current, label: current });
  }
  return options;
}
/**
 * Whether the admin edited anything. Carrying the file's own fields forward is not an
 * edit, so a pristine form must keep Save disabled (re-submitting identical content is a
 * pointless write, and an empty payload would clear the file).
 */
export function hasFormChanges(
  values: RagConfigFormValues,
  view: RagConfigView,
): boolean {
  const seeded = formValuesFromConfig(view);
  const edited = (a: string, b: string) => a.trim() !== b.trim();
  return (
    TEXT_FIELDS.some((key) => edited(values[key], seeded[key])) ||
    NUMERIC_FIELDS.some((key) => edited(values[key], seeded[key])) ||
    SECRET_FIELDS.some((key) => edited(values[key], seeded[key])) ||
    SELECT_FIELDS.some((key) => values[key] !== seeded[key]) ||
    THINKING_FIELDS.some((key) => values[key] !== seeded[key]) ||
    (["asr_provider", "asr_model"] as const).some((key) =>
      edited(values.video[key], seeded.video[key]),
    )
  );
}

/** The bits of a configured model the caption picker needs. */
export interface VisionModelSource {
  name: string;
  model: string;
  display_name?: string | null;
  supports_vision?: boolean;
  provider?: string | null;
}

/**
 * Whether an entry can serve as the caption VLM: it has to declare vision support.
 *
 * The provider decides the *protocol*, not the eligibility — the caption client speaks both
 * the OpenAI shape and Anthropic's Messages shape, choosing by the entry's `use:` class
 * (spec 2026-09-18). So an Anthropic entry is listed here like any other.
 */
export function isCaptionCapable(model: VisionModelSource): boolean {
  return Boolean(model.supports_vision);
}

/**
 * Options for the caption (VLM) picker: the entries that can actually serve it, an explicit
 * "use the configured default" entry, and — through `modelReferenceOptions` — a stored value
 * that names no entry, so opening the form cannot silently drop it. Values are entry *names*:
 * the backend resolves the endpoint and key from that entry, which is why this row needs no
 * endpoint and no key input.
 */
export function visionReferenceOptions(
  models: readonly VisionModelSource[],
  current: string,
  noneLabel: string,
): ModelReferenceOption[] {
  return modelReferenceOptions(models.filter(isCaptionCapable), current, noneLabel);
}
