"use client";

import { ChevronDown, ChevronRight, Lock } from "lucide-react";
import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectSeparator,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tooltip } from "@/components/workspace/tooltip";
import { useI18n } from "@/core/i18n/hooks";
import {
  useKnowledgeBases,
  useReindexKnowledgeBase,
  useReindexStatus,
} from "@/core/knowledge/hooks";
import { isReindexRunning } from "@/core/knowledge/reindex-status";
import { useModels, useModelsConfig } from "@/core/models/hooks";
import { RagConfigRequestError } from "@/core/rag/api";
import {
  ASR_LOCAL_ENGINES,
  ASR_MODEL_MENU,
  ASR_PROVIDER_OPTIONS,
  asrModelForProviderSwitch,
  asrProbeBlocksSave,
  asrProbeVerdictFor,
  buildRagConfigInput,
  changesEmbeddingDimension,
  connectivityProbeKey,
  dimensionProbeKey,
  EMBEDDING_PROVIDER_OPTIONS,
  EMBEDDING_SPARSE_SOURCE_OPTIONS,
  formValuesFromConfig,
  hasFormChanges,
  isCaptionCapable,
  isEmbeddingChange,
  endpointPlaceholderFor,
  isSparseProviderOptionDisabled,
  isSparseServiceUnconfigured,
  isSparseSourceUnsupported,
  MODEL_REFERENCE_NONE,
  modelReferenceOptions,
  PARSE_LANGUAGE_OPTIONS,
  PARSE_MODEL_VERSION_OPTIONS,
  PARSE_TIER_OPTIONS,
  PARSE_PROVIDER_OPTIONS,
  RERANK_PROVIDER_OPTIONS,
  resolveSparseCapability,
  SPARSE_PROVIDER_OPTIONS,
  shouldProbeAsr,
  shouldProbeSparseService,
  sparseProbeKey,
  sparseServiceProbeKey,
  sparseServiceVerdictFor,
  visionReferenceOptions,
  type RagConfigFormValues,
} from "@/core/rag/config-form";
import {
  useProbeAsrService,
  useProbeConnectivity,
  useProbeDimensions,
  useProbeSparseCapability,
  useProbeSparseService,
  useRagConfig,
  useRagMigrationStatus,
  useSaveRagConfig,
} from "@/core/rag/hooks";
import { isMigrationRunning } from "@/core/rag/migration-status";
import {
  AUTOFILL_OFF_INPUT_PROPS,
  SECRET_INPUT_AUTOFILL_PROPS,
} from "@/lib/input-autofill";
import { cn } from "@/lib/utils";

import { DimensionMigrationDialog } from "./dimension-migration-dialog";
import { InfoTip } from "./info-tip";
import { ReindexDialog } from "./reindex-dialog";

/** Sentinel for "no value" — Radix Select rejects an empty item value. */
const AUTO_OPTION_VALUE = "__auto__";

/** Rows the retrieval group's advanced section holds; its trigger names that count. */
const ADVANCED_SETTING_COUNT = 6;

/** The credential the capability probe needs before it can call anything. */
const EMBEDDING_KEY_SOURCE = "embedding_api_key";

/**
 * How long the form waits before probing a newly typed candidate. Each probe is one real embedding
 * call against the platform, so the wait is about not billing a call per keystroke.
 */
const PROBE_DEBOUNCE_MS = 400;

/**
 * The ASR dropdown's three groups (spec 2026-09-28 D2「三组四值」): the two engines that run
 * inside this process, then one row per protocol family. The ids mirror the backend allowlist
 * like every other option list here; the grouping is the row's own reading of them.
 */
const ASR_PROVIDER_GROUPS = [
  { labelKey: "asrGroupLocal" as const, ids: ASR_LOCAL_ENGINES },
  { labelKey: "asrGroupProtocol" as const, ids: ["openai-audio"] },
  { labelKey: "asrGroupNative" as const, ids: ["dashscope"] },
] as const;

/**
 * A provider dropdown. Its ids come from the backend's curated allowlist; the empty id means
 * "let the downstream service decide", which is what the wire carries as null.
 *
 * `disabledReasons` greys out an individual option *and* says why: an option nobody can pick and
 * nobody can explain reads as a broken control, and the reason would otherwise only reach the
 * admin who scrolls to the alert at the bottom of the section.
 *
 * `trailing` is a slot inside the trigger, after the value and before the chevron. A mark that
 * describes the field belongs in the field: the trigger is a fixed-height box, so nothing moves
 * when the mark appears or goes — whereas the same mark on a line of its own pushed every row
 * below it down and back on each open. It is deliberately a *sibling* of `SelectValue` and not a
 * child: Radix mirrors the selected item's text into the trigger, so a child would also be
 * copied into the option labels.
 *
 * `groups` turns the flat list into labelled sections separated by hairlines (spec 2026-09-28
 * D2): the ASR row's four values are two *kinds* of thing — engines and protocols — and a flat
 * list of four makes the admin read all four to find the split. The ids still come from
 * `options`; a group only says where they sit.
 */
function OptionSelect({
  label,
  value,
  options,
  labels,
  groups,
  disabledReasons,
  trailing,
  onChange,
}: {
  label: string;
  value: string;
  options: readonly string[];
  labels: Record<string, string>;
  groups?: readonly { labelKey: string; label: string; ids: readonly string[] }[];
  disabledReasons?: Partial<Record<string, string>>;
  trailing?: React.ReactNode;
  onChange: (next: string) => void;
}) {
  const renderOption = (option: string) => {
    const reason = disabledReasons?.[option];
    return (
      <SelectItem
        key={option || AUTO_OPTION_VALUE}
        value={option || AUTO_OPTION_VALUE}
        disabled={Boolean(reason)}
      >
        {reason
          ? `${labels[option] ?? option} · ${reason}`
          : (labels[option] ?? option)}
      </SelectItem>
    );
  };
  return (
    <Select
      value={value || AUTO_OPTION_VALUE}
      onValueChange={(next) =>
        onChange(next === AUTO_OPTION_VALUE ? "" : next)
      }
    >
      <SelectTrigger className="w-full min-w-0" aria-label={label}>
        <SelectValue />
        {trailing ? (
          <span className="text-muted-foreground ml-auto shrink-0 text-xs">
            {trailing}
          </span>
        ) : null}
      </SelectTrigger>
      <SelectContent>
        {groups
          ? groups.map((group, index) => (
              <Fragment key={group.labelKey}>
                {index > 0 && <SelectSeparator />}
                <SelectGroup>
                  <SelectLabel>{group.label}</SelectLabel>
                  {group.ids.map(renderOption)}
                </SelectGroup>
              </Fragment>
            ))
          : options.map(renderOption)}
      </SelectContent>
    </Select>
  );
}

/**
 * One row of the form: the label sits in a fixed gutter, so every value column lines up no
 * matter how long the labels are. Two values = the two retrieval roles, one = an ordinary row.
 */
const ROW =
  "grid grid-cols-[8rem_minmax(0,1fr)] items-center gap-x-4 py-3 max-md:grid-cols-1 max-md:gap-y-1";
const ROW_PAIR =
  "grid grid-cols-[8rem_minmax(0,1fr)_minmax(0,1fr)] items-center gap-x-4 py-3";

/**
 * Hairlines between rows; with the shared gutter they are what makes a group read as one form.
 * `stacked` marks the two-value group: below `md` its rows go `contents` and the cells regroup
 * into one block per role (spec 2026-09-24 §3.2 revision — 整列分组), so the wrapper must lay
 * them out in one column and give up the per-row hairlines (one divider lives in the group).
 */
function Rows({
  children,
  stacked,
}: {
  children: React.ReactNode;
  stacked?: boolean;
}) {
  return (
    <div
      className={cn(
        "divide-y",
        stacked && "max-md:flex max-md:flex-col max-md:gap-2 max-md:divide-y-0",
      )}
    >
      {children}
    </div>
  );
}

/**
 * A row that only exists because of the row above it: indented behind a rule, so the scope is
 * shown instead of spelled out — the sparse rows used to repeat 「稀疏」 five times to say what
 * this indent says once (2026-09-16).
 */
const NESTED_GUTTER = "ml-3 border-l border-border pl-3";

/** The gutter cell: the visible label, plus an ⓘ when there is a sentence for it. */
function RowLabel({
  children,
  className,
  info,
  nested,
}: {
  children: React.ReactNode;
  className?: string;
  info?: string;
  nested?: boolean;
}) {
  return (
    <span
      className={cn(
        "text-muted-foreground flex items-center gap-1 text-xs",
        nested && NESTED_GUTTER,
        className,
      )}
    >
      {children}
      {info && <InfoTip text={info} />}
    </span>
  );
}

/**
 * One value cell of a two-value row. Below `md` the wrapper stacks the shared field label above
 * the control and the group's cells regroup under one role heading per block (spec 2026-09-24
 * §3.2 revision: 整列分组 — one heading and one divider per role block, not per row); at `md`
 * and up the wrapper is `contents`, so the wide grid still sees the bare control unchanged.
 */
function PairCell({
  label,
  order,
  children,
}: {
  label: string;
  order: string;
  children: React.ReactNode;
}) {
  return (
    <div className={cn("flex min-w-0 flex-col gap-1 md:contents", order)}>
      <span className="text-muted-foreground text-xs md:hidden">{label}</span>
      {children}
    </div>
  );
}

/** A role heading: the bold role name. The English pill is gone (spec §3.2 revision, 乙). */
/** The four states one leg's dot can be in (spec 2026-09-26 D5-5). */
type LegDotState =
  | "untested"
  | "probing"
  | "ok"
  | "bad-dimension"
  | "bad-half"
  | "bad";

const LEG_DOT_TONE: Record<LegDotState, string> = {
  untested: "bg-muted-foreground/40",
  probing: "bg-muted-foreground/40 animate-pulse",
  ok: "bg-emerald-500",
  // 橙是他定的：与「没答案」的灰分开，也与既有失败色 destructive 分开。
  "bad-dimension": "bg-amber-500",
  // 三橙同色、理由不同：连不上 / 要不到该维度 / 连得上但没给稀疏那一半。
  "bad-half": "bg-amber-500",
  bad: "bg-amber-500",
};

/**
 * A role heading that doubles as its leg's connectivity button (D5-5).
 *
 * The dot after the title carries the state and the whole title is the control: one real call per
 * click, nothing persisted. The hover sentence is the server's own `detail` when there is one, so
 * the row never paraphrases a reason it did not receive.
 */
function LegHeading({
  label,
  status,
  reason,
  disabled,
  onProbe,
}: {
  label: string;
  status: LegDotState;
  reason: string;
  disabled: boolean;
  onProbe: () => void;
}) {
  return (
    <Tooltip content={reason} contentClassName="max-w-xs">
      <button
        type="button"
        data-slot="leg-heading"
        data-state={status}
        aria-label={`${label} · ${reason}`}
        disabled={disabled}
        onClick={onProbe}
        className={cn(
          // `inline-flex` + `text-left` 是为了回到原来的位置：原来的标题是个 `<span>`（按内容宽、
          // 贴左），换成 `<button>` 后浏览器默认撑满整格并把内容居中 —— 标题会飘到列中间。
          "inline-flex items-center text-left text-sm font-semibold",
          !disabled && "hover:text-foreground/80 cursor-pointer",
          disabled && "cursor-not-allowed",
        )}
      >
        {label}
        <span
          aria-hidden
          data-slot="leg-dot"
          className={cn(
            "ml-1.5 inline-block size-2 rounded-full align-middle",
            LEG_DOT_TONE[status],
          )}
        />
      </button>
    </Tooltip>
  );
}

/**
 * The stand-in text of a field that holds no value of its own: the reason a row is locked, and
 * the note that a credential arrives from the environment. Same message, so same type and same
 * weight — they sit in comparable rows and used to differ in size, side and tint (2026-09-16).
 */
const PLACEHOLDER_TEXT = "text-muted-foreground/70 text-sm";

/**
 * A value the current provider fixes — shown rather than hidden (2026-09-15): a control that
 * vanishes when you switch provider reads as a missing feature, and the tallest cell used to
 * push its neighbour out of alignment. The box states *why* it is locked.
 */
function LockedBox({
  reason,
  value,
}: {
  reason: string;
  /** Only ever a non-secret value; secret rows pass nothing and show the reason alone. */
  value?: string;
}) {
  return (
    <div className="border-input bg-muted/40 text-muted-foreground flex h-9 items-center justify-between gap-2 rounded-md border px-3">
      {/* A blank or absent value shows the reason: the box must never look editable-empty. */}
      <span className={cn("truncate", !value?.trim() && PLACEHOLDER_TEXT)}>
        {value?.trim() ? value : reason}
      </span>
      <Lock className="size-3.5 shrink-0" aria-hidden="true" />
    </div>
  );
}

/**
 * A credential input whose provenance chip rides *inside* the field (2026-09-16): set beside
 * the box it squeezed the box — worst on the retrieval pair, where the row then had to hold
 * two of them. Inside, it costs the field a slice of its own padding instead of the row's width.
 *
 * It leads the field while the field is untouched, like a locked row's reason does, and clears
 * the moment the field becomes yours — on focus, or because something is typed in it. It is a
 * note about provenance, not a placeholder for a format: left up while typing it reads as part
 * of the value, and the text typed after it looks appended to the note.
 *
 * `env`-sourced fields come back from the API empty (the environment holds the secret), so a
 * chip next to a non-empty field can only mean an override is being typed — never a stored key.
 */
function SecretInput({
  badge,
  className,
  value,
  ...props
}: React.ComponentProps<"input"> & { badge?: string }) {
  const [focused, setFocused] = useState(false);
  const showBadge = Boolean(badge) && !focused && !value;

  return (
    <div className={cn("relative w-full min-w-0", className)}>
      <Input
        type="password"
        className={showBadge ? "pl-32" : undefined}
        value={value}
        onFocus={() => setFocused(true)}
        onBlur={() => setFocused(false)}
        {...SECRET_INPUT_AUTOFILL_PROPS}
        {...props}
      />
      {showBadge && (
        <span
          className={cn(
            "pointer-events-none absolute top-1/2 left-3 -translate-y-1/2",
            PLACEHOLDER_TEXT,
          )}
        >
          {badge}
        </span>
      )}
    </div>
  );
}

/**
 * RAG functional-model editor (spec 2026-09-10 rag functional-model config §5, extended by
 * spec 2026-09-14 rag model provider adaptation §4.1).
 *
 * Every group reads as the same form: a label gutter on the left, values on the right, rows
 * separated by a hairline. The retrieval group is the one two-value form — 向量 and 重排 are
 * peers with identical row structure, so their row labels are written **once** in the gutter
 * instead of once per column. The sparse settings live behind an advanced disclosure because
 * three of them only matter in one configuration.
 *
 * The three model-reference rows (graph extraction, eval judge, caption VLM) are plain pickers
 * over the configured `models:` entries: the backend resolves what each role needs from the
 * named entry, so none of them asks for an endpoint or a key of its own. The embedding and
 * rerank rows are the exception — they select a *provider* from the backend's curated
 * allowlist and carry an endpoint, because those clients are not model-entry based. A provider
 * that ships its own address shows that row **locked** rather than hidden.
 *
 * Saving replaces the whole `rag_config.json` object, so Save stays disabled until the admin
 * actually edits something (see `hasFormChanges`).
 */
export function FunctionalModelsView() {
  const { t } = useI18n();
  const M = t.settings.models;
  const F = t.settings.functionalModels;
  const { view, isLoading, error } = useRagConfig();
  const save = useSaveRagConfig();
  const migration = useRagMigrationStatus();
  const migrationRunning = isMigrationRunning(migration.data);
  const migrationProgress = migration.data?.progress;
  const probe = useProbeSparseCapability();
  const sparseServiceProbe = useProbeSparseService();
  const dimensionProbe = useProbeDimensions();
  // 一条腿一个实例：结论是「按腿」的，共用一个 mutation 只会留下最后一发 —— 那样两条腿
  // 永远只有一条亮（点另一条就把前一条打回灰）。
  const embeddingConnectivity = useProbeConnectivity();
  const rerankConnectivity = useProbeConnectivity();
  // 一行一个实例：ASR 那格的结论与两条腿无关，共用只会互相顶掉。
  const asrProbe = useProbeAsrService();
  const requestedDimension = useRef<string | null>(null);
  const { models } = useModels();
  const { config: modelsConfig } = useModelsConfig();

  const [values, setValues] = useState<RagConfigFormValues | null>(null);
  // The last candidate a probe was actually sent for, so re-rendering (or unrelated typing) does
  // not repeat the same call — and so a *new* candidate always does get one.
  const requestedProbe = useRef<string | null>(null);
  // Same idea for the sparse-service probe: one call per distinct candidate.
  const requestedSparseServiceProbe = useRef<string | null>(null);
  // The rebuild entry is library-scoped while this view is app-wide, so the target is picked
  // here (session-only) instead of being derived from wherever the dialog was opened.
  const [reindexKbId, setReindexKbId] = useState("");
  const [reindexOpen, setReindexOpen] = useState(false);
  const [dimensionConfirmOpen, setDimensionConfirmOpen] = useState(false);
  // Why the server could not verify the configuration it just saved (spec 2026-09-17 save-time
  // probe §3 D3). It describes what is *in force*, so it lasts until the next save reports its own
  // verdict rather than being cleared by the next keystroke.
  const [saveWarning, setSaveWarning] = useState<string | null>(null);
  const { data: knowledgeBases } = useKnowledgeBases();
  const reindexStatus = useReindexStatus(reindexKbId || null);
  const reindex = useReindexKnowledgeBase(reindexKbId || null);

  useEffect(() => {
    if (!view) return;
    setValues(formValuesFromConfig(view));
  }, [view]);

  const payload = useMemo(
    () => (view && values ? buildRagConfigInput(values, view) : {}),
    [values, view],
  );
  const hasChanges = values && view ? hasFormChanges(values, view) : false;
  const embeddingChanged =
    view && values ? isEmbeddingChange(values, view) : false;

  // The endpoint rows are always editable (spec 2026-09-25 rag-endpoint-unlock): the same vendor
  // may serve different addresses (Bailian workspace-scoped endpoints), so no lock and no
  // restore-to-default — the capability block's default endpoint is only the grey placeholder
  // hint (never a value, never a runtime fallback).
  const embeddingEndpointPlaceholder = endpointPlaceholderFor(
    view?.embedding_providers,
    values?.embedding_provider ?? "",
  );
  const rerankEndpointPlaceholder = endpointPlaceholderFor(
    view?.rerank_providers,
    values?.rerank_provider ?? "",
  );

  // The ASR row's own probe (spec 2026-09-28 D7): only the service tiers reach out, the
  // verdict counts only for the values it was taken for, and only `no_timestamps` blocks a save.
  // 手动探针 2026-09-30 起零入口休眠（用户裁定）——判定与拦保存留着，只是没有可点的控件。
  const asrKeyPresent = view?.sources?.asr_api_key !== "unset";
  const asrServiceApplies = values ? shouldProbeAsr(values) : false;
  const asrVerdict = values
    ? asrProbeVerdictFor(values, asrKeyPresent, asrProbe.data ?? null)
    : null;
  const asrBlockReason =
    asrServiceApplies && asrProbeBlocksSave(asrVerdict)
      ? F.asrProbeBlocksSave
      : null;

  // The sparse half's capability is a three-state answer (spec 2026-09-16 §3 D2): the allowlist
  // settles the dialect question, a probe settles the model question, and everything unproven
  // stays `unknown` — which blocks nothing.
  const probeVerdict = probe.data ?? null;
  const sparseCapability = values
    ? resolveSparseCapability(values, view?.embedding_providers, probeVerdict)
    : "unknown";
  // Judged from the form's own provider, so switching the picker warns immediately.
  const sparseUnsupported = values
    ? isSparseSourceUnsupported(values, view?.embedding_providers, probeVerdict)
    : false;
  // Two combinations are refused by the runtime on sight; both say so while editing, and the same
  // sentence rides next to Save (a disabled button without a reason reads as a broken button).
  const sparseBlockReason = sparseUnsupported
    ? F.sparseProviderUnsupported
    : values && isSparseServiceUnconfigured(values)
      ? F.sparseServiceUnconfigured
      : null;
  // Endpoint addresses are required (spec 2026-09-25 rag-endpoint-unlock D3): there is no silent
  // default to fall back on, so an empty address stops the save with its own sentence.
  const endpointRequiredReason =
    values &&
    (!values.embedding_base_url.trim() || !values.rerank_base_url.trim())
      ? F.endpointRequired
      : null;
  const saveBlockReason =
    sparseBlockReason ?? endpointRequiredReason ?? asrBlockReason;
  const sparseUnverified =
    values?.embedding_sparse_source === "provider" &&
    probeVerdict?.key === (values ? sparseProbeKey(values) : "") &&
    probeVerdict.status === "unverifiable";

  // Probe only when the question can actually be asked: the allowlist says this provider *can*
  // supply the sparse half, the form is asking it for that half, a model is named, and there is a
  // key to call with. The key test is `sources[...] !== "unset"` and NOT "the input box is not
  // empty" — an environment-backed key arrives as an empty box, and reading that as "no key" would
  // leave the feature dead in exactly the deployment that needs it.
  const probeApplies =
    view !== undefined &&
    values !== null &&
    values.embedding_sparse_source === "provider" &&
    values.embedding_model.trim() !== "" &&
    view.sources?.[EMBEDDING_KEY_SOURCE] !== "unset" &&
    view.embedding_providers?.some(
      (provider) =>
        provider.provider_id === values.embedding_provider &&
        provider.emits_sparse,
    ) === true;

  useEffect(() => {
    if (!probeApplies || !values) return;
    const key = sparseProbeKey(values);
    if (requestedProbe.current === key) return;
    // One real (billable) embedding call per candidate: without the pause, a six-character model
    // id would be six calls, five of them for ids that do not exist.
    const timer = setTimeout(() => {
      requestedProbe.current = key;
      probe.mutate({
        key,
        embedding_provider: values.embedding_provider,
        embedding_model: values.embedding_model.trim(),
        embedding_base_url: values.embedding_base_url.trim() || null,
        embedding_api_key: values.embedding_api_key.trim() || null,
      });
    }, PROBE_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [probeApplies, values, probe]);

  // The external sparse service gets the same treatment (connectivity spec §3 D4): a wrong port or
  // a service that is not up used to surface as "some chunks failed" at ingest time, and the whole
  // point of this probe is that the admin hears about it while still editing. A key counts as
  // *existing* when the deployment stores one or the environment backs it — reading "the box is
  // empty" as "no key" would probe without one and call a healthy service unreachable.
  const sparseServiceHasKey =
    (values?.sparse_api_key.trim() ?? "") !== "" ||
    (view?.sources?.sparse_api_key ?? "unset") !== "unset";
  const sparseServiceApplies = values
    ? shouldProbeSparseService(values)
    : false;
  const sparseServiceVerdict = values
    ? sparseServiceVerdictFor(
        values,
        sparseServiceHasKey,
        sparseServiceProbe.data ?? null,
      )
    : null;
  const sparseServiceStatus = sparseServiceProbe.isPending
    ? { text: F.sparseProbing, tone: "text-muted-foreground" }
    : sparseServiceVerdict?.status === "unreachable"
      ? { text: F.sparseServiceUnreachable, tone: "text-destructive" }
      : sparseServiceVerdict?.status === "empty"
        ? { text: F.sparseServiceEmpty, tone: "text-destructive" }
        : null;

  useEffect(() => {
    if (!sparseServiceApplies || !values) return;
    const key = sparseServiceProbeKey(values, sparseServiceHasKey);
    if (requestedSparseServiceProbe.current === key) return;
    const timer = setTimeout(() => {
      requestedSparseServiceProbe.current = key;
      sparseServiceProbe.mutate({
        key,
        sparse_provider: values.sparse_provider,
        sparse_base_url: values.sparse_base_url.trim() || null,
        sparse_api_key: values.sparse_api_key.trim() || null,
      });
    }, PROBE_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [sparseServiceApplies, sparseServiceHasKey, values, sparseServiceProbe]);

  // ── 维度探测 + 两腿的连通点 (spec 2026-09-26 §3 / D5-5) ────────────────────
  // 有钥匙 = 存的或环境变量（判据同稀疏探针）——空输入框不算「没有」，否则 env 部署会死在
  // 这里。维度探测不读 sparse_source：它问的是模型吃哪些宽度。
  const embeddingKeyPresent = view?.sources?.[EMBEDDING_KEY_SOURCE] !== "unset";
  const rerankKeyPresent = view?.sources?.rerank_api_key !== "unset";
  const dimensionKey = values ? dimensionProbeKey(values) : "";
  const dimensionVerdict =
    dimensionProbe.data && dimensionProbe.data.key === dimensionKey
      ? dimensionProbe.data
      : null;
  const dimensionProbing =
    dimensionProbe.isPending && dimensionProbe.variables?.key === dimensionKey;

  /** 框内状态点：只在不"绿"时才出现，理由走它自己的提示气泡（dark Tooltip，与两条腿同族）。 */
  const dimensionState: { state: "probing" | "unprobed" | "no-tiers"; reason: string } | null = dimensionProbing
    ? { state: "probing", reason: F.dimensionProbing }
    : dimensionVerdict === null
      ? null
      : dimensionVerdict.status === "unreachable"
        ? { state: "unprobed", reason: `${F.dimensionUnprobed}：${dimensionVerdict.detail}` }
        : dimensionVerdict.type === "tiered" && dimensionVerdict.values.length === 0
          ? { state: "no-tiers", reason: F.dimensionNoTiers }
          : null;
  const dimensionApplies =
    values !== null &&
    values.embedding_model.trim() !== "" &&
    values.embedding_base_url.trim() !== "" &&
    embeddingKeyPresent;

  useEffect(() => {
    if (!dimensionApplies || !values) return;
    const key = dimensionProbeKey(values);
    if (requestedDimension.current === key) return;
    // 真实调用、按 key 只发生一次（改 provider / Model / 地址才换 key）。
    const timer = setTimeout(() => {
      requestedDimension.current = key;
      dimensionProbe.mutate({
        key,
        embedding_provider: values.embedding_provider,
        embedding_model: values.embedding_model.trim(),
        embedding_base_url: values.embedding_base_url.trim() || null,
        embedding_api_key: null,
      });
    }, PROBE_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [dimensionApplies, values, dimensionProbe]);

  useEffect(() => {
    // ③ 型（不吃参数）只有唯一一个可取值 ⇒ 行是只读的，那就必须把那个值**填进去**，不能只当占位提示：
    // 留空 = 1024，而一个原生 768 的固定型模型于是永远保存不过（保存期探针会拒），用户还没有输入口。
    if (dimensionVerdict?.type !== "fixed" || dimensionVerdict.native === null) return;
    const native = String(dimensionVerdict.native);
    setValues((prev) =>
      prev && prev.embedding_dimension !== native
        ? { ...prev, embedding_dimension: native }
        : prev,
    );
  }, [dimensionVerdict]);

  /** 一条腿的连通点：坐标齐了才可点；结论只认「点过的那一发」。 */
  const legProps = (form: RagConfigFormValues, leg: "embedding" | "rerank") => {
    const provider =
      leg === "embedding" ? form.embedding_provider : form.rerank_provider;
    const model = (
      leg === "embedding" ? form.embedding_model : form.rerank_model
    ).trim();
    const baseUrl = (
      leg === "embedding" ? form.embedding_base_url : form.rerank_base_url
    ).trim();
    const hasKey = leg === "embedding" ? embeddingKeyPresent : rerankKeyPresent;
    const ready = model !== "" && baseUrl !== "" && hasKey;
    const probe =
      leg === "embedding" ? embeddingConnectivity : rerankConnectivity;
    const key = connectivityProbeKey(leg, form, hasKey);
    const verdict =
      probe.data && probe.data.key === key ? probe.data : null;
    const probing = probe.isPending && probe.variables?.key === key;
    const status: LegDotState = probing
      ? "probing"
      : !ready || verdict === null
        ? "untested"
        : verdict.status === "ok"
          ? "ok"
          : verdict.status === "dimension_unavailable"
            ? "bad-dimension"
            : verdict.status === "half_missing"
              ? "bad-half"
              : "bad";
    const reason = probing
      ? F.legDotProbing
      : !ready
        ? F.legDotNeedsConfig
        : verdict
          ? verdict.detail
          : F.legDotUntested;
    return {
      status,
      reason,
      disabled: !ready || probing,
      onProbe: () => {
        const rawDimension = form.embedding_dimension.trim();
        probe.mutate({
          key,
          leg,
          provider,
          model,
          base_url: baseUrl || null,
          api_key: null,
          embedding_dimension:
            leg === "embedding" && rawDimension !== "" ? Number(rawDimension) : null,
        });
      },
    };
  };

  /** 档位快捷项：① 型 = 探到的有效档；② 型 = ≤ 原生的候选；③ 型没有档位区。 */
  const dimensionTiers = (() => {
    const verdict = dimensionVerdict;
    if (!verdict || verdict.status !== "ok") return [] as number[];
    // ① 型 = 探到的有效档；② 型 = ≤ 原生的候选（静态提示）；③ 型没有档位。
    if (verdict.type === "tiered") return verdict.values;
    if (verdict.type === "range" && verdict.native !== null) {
      return verdict.candidates.filter((width) => width <= (verdict.native ?? 0));
    }
    return [] as number[];
  })();

  if (isLoading) {
    return <div className="text-muted-foreground text-sm">{t.common.loading}</div>;
  }
  if (error instanceof RagConfigRequestError && error.isAdminRequired) {
    return <div className="text-muted-foreground text-sm">{M.adminRequired}</div>;
  }
  if (error) {
    return <div>Error: {error.message}</div>;
  }
  if (!view || !values) {
    return null;
  }

  const sources = view.sources ?? {};
  const managedModels = modelsConfig?.models ?? [];
  const visionOptions = visionReferenceOptions(
    managedModels,
    values.vlm_model,
    F.vlmModelDefault,
  );
  const hasVisionModel = managedModels.some(isCaptionCapable);

  // Ids come from the backend's curated allowlist; the empty id is "let the service decide".
  const PROVIDER_LABELS: Record<string, string> = {
    dashscope: F.providerDashscope,
    "volcengine-ark": F.providerVolcengineArk,
    "openai-compatible": F.providerOpenAIChat,
    "generic-rerank": F.providerGenericRerank,
    "tei-rerank": F.providerTeiRerank,
    "tei-sparse": F.providerTeiSparse,
    "mineru-cloud": F.providerMineruCloud,
    "mineru-local": F.providerMineruLocal,
    "": F.parseTierAuto,
  };
  const SPARSE_SOURCE_LABELS: Record<string, string> = {
    provider: F.sparseSourceProvider,
    external: F.sparseSourceExternal,
    bm25: F.sparseSourceBm25,
  };
  // The sparse service gets its own label map for the empty id: the shared one borrows the parse
  // tier's wording ("let the service decide"), which is true there and meaningless here — on
  // this row `""` is simply "not chosen", and the runtime refuses it.
  const SPARSE_SERVICE_LABELS: Record<string, string> = {
    "": F.sparseProviderNone,
    "tei-sparse": F.providerTeiSparse,
  };
  // The two cloud-only parse knobs name their own empty option, like the sparse service:
  // on the wire it means "not declared here", so the configured default applies.
  const PARSE_LANGUAGE_LABELS: Record<string, string> = {
    "": F.parseLanguageDefault,
  };
  const PARSE_MODEL_VERSION_LABELS: Record<string, string> = {
    "": F.parseModelVersionDefault,
  };

  function update<K extends keyof RagConfigFormValues>(
    key: K,
    value: RagConfigFormValues[K],
  ) {
    setValues((prev) => (prev ? { ...prev, [key]: value } : prev));
  }

  function updateVideo(key: keyof RagConfigFormValues["video"], value: string) {
    setValues((prev) =>
      prev ? { ...prev, video: { ...prev.video, [key]: value } } : prev,
    );
  }

  /** Provenance is state, not documentation: a chip when the environment supplies it. */
  function isEnvBacked(field: string) {
    return sources[field] === "env";
  }

  /** The overwrite warning, shown once per row even though the pair holds two credentials. */
  function secretHintFor(...fields: string[]) {
    return fields.some((field) => sources[field] === "ui")
      ? F.secretHint
      : undefined;
  }

  function handleSave() {
    if (!hasChanges) return;
    // A width change rebuilds every library before it can take effect (spec 2026-09-26 D5-7),
    // so it asks first — the rest of the save lands immediately either way.
    if (view && values && changesEmbeddingDimension(values, view)) {
      setDimensionConfirmOpen(true);
      return;
    }
    submitSave();
  }

  function submitSave() {
    save.mutate(payload, {
      onSuccess: (saved) => {
        toast.success(F.saved);
        setSaveWarning(saved.warning ?? null);
        // 迁移在飞时，PUT 响应里的宽度仍是「当前生效」的旧值（这是设计），而表单里该显示
        // 用户刚选的那个 —— 否则响应回填会把它改回去，下一次保存就悄悄触发反向迁移。
        const pending = saved.migration;
        if (pending?.state === "running") {
          setValues((prev) =>
            prev
              ? { ...prev, embedding_dimension: String(pending.target_dimension) }
              : prev,
          );
        }
      },
    });
  }

  function handleDimensionConfirm() {
    setDimensionConfirmOpen(false);
    submitSave();
  }

  const libraries = knowledgeBases ?? [];
  const selectedKb = libraries.find((kb) => kb.id === reindexKbId);
  const reindexRunning = isReindexRunning(reindexStatus.data, reindex.isPending);
  const reindexProgress = reindexStatus.data?.progress;

  function handleReindexConfirm() {
    reindex.mutate(undefined, {
      onSuccess: (ack) => {
        if (ack.status === "already_running") {
          toast.info(F.reindexAlreadyRunning);
        } else {
          toast.success(F.reindexEnqueued);
        }
        setReindexOpen(false);
      },
    });
  }

  const sparseExternal = values.embedding_sparse_source === "external";

  // The thinking toggle menu (spec 2026-10-03 D1=甲): rows are the five *role slots* — a
  // model shared by two roles is two independent rows. Each row shows the model its slot
  // currently points at, so the menu reads as "which role, on what".
  const thinkingRows = (
    [
      ["extract_thinking", F.extractModel, "extract_model", F.extractModelNone],
      ["wiki_thinking", F.wikiModel, "wiki_model", F.wikiModelNone],
      ["judge_thinking", F.judgeModel, "judge_model", F.judgeModelNone],
      ["synthesis_thinking", F.synthesisModel, "synthesis_model", F.synthesisModelNone],
      ["vlm_thinking", F.captionModel, "vlm_model", F.vlmModelDefault],
    ] as const
  ).map(([key, label, modelField, noneLabel]) => {
    const modelValue = values[modelField];
    return {
      key,
      label,
      checked: values[key],
      modelLabel:
        modelReferenceOptions(models, modelValue, noneLabel).find(
          (option) => option.value === (modelValue || MODEL_REFERENCE_NONE),
        )?.label ?? noneLabel,
    };
  });
  const thinkingCount = thinkingRows.filter((row) => row.checked).length;

  return (
    <div className="flex w-full flex-col gap-4">
      {/* The RAG-wide default (spec 2026-09-23 D4): above the role settings because it is the
          fallback every one of them reads, and in the same card + title + ⓘ shape they use. */}
      <Group title={F.defaultModel} info={F.defaultModelHint}>
        <Select
          value={values.default_model || MODEL_REFERENCE_NONE}
          onValueChange={(next) =>
            update("default_model", next === MODEL_REFERENCE_NONE ? "" : next)
          }
        >
          <SelectTrigger className="w-full min-w-0" aria-label={F.defaultModel}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {modelReferenceOptions(
              models,
              values.default_model,
              F.defaultModelNone,
            ).map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        {/* The follow-chat thinking menu: no label in front — the trigger names itself and
            its tail carries the state (idle hint → selected count), per his UI rule. The
            trigger borrows SelectTrigger's own surface (border-input / bg-transparent): a
            Button outline's bg-background reads as a tinted box beside its sibling. */}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              type="button"
              variant="outline"
              aria-label={F.thinkingMenuLabel}
              className="mt-4 w-full justify-between border-input bg-transparent font-normal"
            >
              {F.thinkingMenuState(thinkingCount)}
              <ChevronDown className="size-4 opacity-50" />
            </Button>
          </DropdownMenuTrigger>
          {/* Stays open across picks: the five roles are one decision, not five. The content is
              a two-column grid and each row spans it as a subgrid, so every model name starts
              at the same x — the aligned columns are what tells role from value now that the
              「·」 is gone (2026-10-06). The aria-label keeps the old "role · model" read for
              assistive tech. */}
          <DropdownMenuContent
            align="start"
            className="grid w-[var(--radix-dropdown-menu-trigger-width)] grid-cols-[max-content_minmax(0,1fr)]"
          >
            {thinkingRows.map((row) => (
              <DropdownMenuCheckboxItem
                key={row.key}
                aria-label={`${row.label} · ${row.modelLabel}`}
                checked={row.checked}
                onCheckedChange={() => update(row.key, !row.checked)}
                onSelect={(event) => event.preventDefault()}
                className="col-span-2 grid grid-cols-subgrid items-center"
              >
                <span data-slot="thinking-role">{row.label}</span>
                <span data-slot="thinking-model">{row.modelLabel}</span>
              </DropdownMenuCheckboxItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
      </Group>

      <Group title={F.groupRetrieval} info={F.groupRetrievalHint}>
        <Rows stacked>
          <div className={`${ROW_PAIR} pt-0 pb-2 max-md:hidden`}>
            <span />
            <LegHeading label={F.embeddingModel} {...legProps(values, "embedding")} />
            <LegHeading label={F.rerankModel} {...legProps(values, "rerank")} />
          </div>

          {/* Below `md` the pair regroups into one block per role (spec 2026-09-24 §3.2
              revision — 整列分组): the bold role heading sits at each block head (the wide
              column heading's own word, pill removed) and a single divider separates the two
              blocks instead of a hairline per row. */}
          <div className="order-1 text-sm font-semibold md:hidden">
            {F.embeddingModel}
          </div>
          <div className="order-6 my-1 border-t border-border md:hidden" />
          <div className="order-7 text-sm font-semibold md:hidden">
            {F.rerankModel}
          </div>

          <div className={`${ROW_PAIR} max-md:contents`}>
            <RowLabel className="max-md:hidden">{F.providerLabel}</RowLabel>
            <PairCell label={F.providerLabel} order="order-2">
              <OptionSelect
                label={F.embeddingProvider}
                value={values.embedding_provider}
                options={EMBEDDING_PROVIDER_OPTIONS}
                labels={PROVIDER_LABELS}
                onChange={(next) =>
                  update(
                    "embedding_provider",
                    next as RagConfigFormValues["embedding_provider"],
                  )
                }
              />
            </PairCell>
            <PairCell label={F.providerLabel} order="order-8">
              <OptionSelect
                label={F.rerankProvider}
                value={values.rerank_provider}
                options={RERANK_PROVIDER_OPTIONS}
                labels={PROVIDER_LABELS}
                onChange={(next) =>
                  update(
                    "rerank_provider",
                    next as RagConfigFormValues["rerank_provider"],
                  )
                }
              />
            </PairCell>
          </div>

          <div className={`${ROW_PAIR} max-md:contents`}>
            <RowLabel className="max-md:hidden">{F.modelLabel}</RowLabel>
            <PairCell label={F.modelLabel} order="order-3">
              <Input
                value={values.embedding_model}
                aria-label={F.embeddingModel}
                {...AUTOFILL_OFF_INPUT_PROPS}
                onChange={(event) =>
                  update("embedding_model", event.target.value)
                }
              />
            </PairCell>
            <PairCell label={F.modelLabel} order="order-9">
              <Input
                value={values.rerank_model}
                aria-label={F.rerankModel}
                {...AUTOFILL_OFF_INPUT_PROPS}
                onChange={(event) => update("rerank_model", event.target.value)}
              />
            </PairCell>
          </div>

          <div className={`${ROW_PAIR} max-md:contents`}>
            <RowLabel
              className="max-md:hidden"
              info={secretHintFor("embedding_api_key", "rerank_api_key")}
            >
              {F.apiKeyLabel}
            </RowLabel>
            <PairCell label={F.apiKeyLabel} order="order-4">
              <SecretInput
                badge={
                  isEnvBacked("embedding_api_key")
                    ? F.secretFromEnvBadge
                    : undefined
                }
                value={values.embedding_api_key}
                aria-label={F.embeddingApiKey}
                onChange={(event) =>
                  update("embedding_api_key", event.target.value)
                }
              />
            </PairCell>
            <PairCell label={F.apiKeyLabel} order="order-10">
              <SecretInput
                badge={
                  isEnvBacked("rerank_api_key")
                    ? F.secretFromEnvBadge
                    : undefined
                }
                value={values.rerank_api_key}
                aria-label={F.rerankApiKey}
                onChange={(event) =>
                  update("rerank_api_key", event.target.value)
                }
              />
            </PairCell>
          </div>

          <div className={`${ROW_PAIR} max-md:contents`}>
            <RowLabel className="max-md:hidden" info={F.retrievalEndpointHint}>
              {F.endpointLabel}
            </RowLabel>
            <PairCell label={F.endpointLabel} order="order-5">
              <Input
                value={values.embedding_base_url}
                aria-label={F.embeddingBaseUrl}
                placeholder={embeddingEndpointPlaceholder}
                {...AUTOFILL_OFF_INPUT_PROPS}
                onChange={(event) =>
                  update("embedding_base_url", event.target.value)
                }
              />
            </PairCell>
            {/* The rerank leg mirrors it (spec 2026-09-25 rag-endpoint-unlock): same rule, its
                own capability block supplies the placeholder hint. */}
            <PairCell label={F.endpointLabel} order="order-11">
              <Input
                value={values.rerank_base_url}
                aria-label={F.rerankBaseUrl}
                placeholder={rerankEndpointPlaceholder}
                {...AUTOFILL_OFF_INPUT_PROPS}
                onChange={(event) =>
                  update("rerank_base_url", event.target.value)
                }
              />
            </PairCell>
          </div>
        </Rows>

        <Collapsible className="mt-5">
          <CollapsibleTrigger className="text-muted-foreground hover:text-foreground group flex items-center gap-1.5 text-xs">
            <ChevronRight className="size-3.5 transition-transform group-data-[state=open]:rotate-90" />
            {F.advancedSettings(ADVANCED_SETTING_COUNT)}
          </CollapsibleTrigger>
          <CollapsibleContent className="mt-4">
            <Rows>
              {/* 维度在上、稀疏来源在下（spec 2026-09-26 D5-4）：维度=库宽、连着全库重建，
                  是这块最重的一项。探测自动跑，行内没有按钮。 */}
              <div className={ROW} data-slot="dimension-row">
                <RowLabel
                  info={[
                    F.dimensionHint,
                    F.dimensionProbeHint,
                    // ③ 型只读：说明为什么改不了（档位菜单在 ③ 不存在，这句只能挂在这里）。
                    dimensionVerdict?.type === "fixed" && dimensionVerdict.native !== null
                      ? F.dimensionFixedHint(dimensionVerdict.native)
                      : null,
                  ]
                    .filter(Boolean)
                    .join(" ")}
                >
                  {F.dimensionLabel}
                </RowLabel>
                {/* 一行：输入框（自由值） + 框内下拉（探到的档位） + 框内状态点。
                    规格：状态必须骑在它描述的字段内，不能自己占一行 —— 行高与相邻行一致。 */}
                <div className="relative w-full" data-slot="dimension-control">
                  <Input
                    inputMode="numeric"
                    aria-label={F.dimensionLabel}
                    data-slot="dimension-input"
                    className="w-full pr-10"
                    value={values.embedding_dimension}
                    readOnly={dimensionVerdict?.type === "fixed"}
                    placeholder={
                      dimensionVerdict?.native ? String(dimensionVerdict.native) : undefined
                    }
                    onChange={(event) =>
                      update("embedding_dimension", event.target.value)
                    }
                    {...AUTOFILL_OFF_INPUT_PROPS}
                  />
                  {/* 触发器**就是整格**（这一层 inset-0 的透明壳），所以下拉锚在整格上、
                      宽度取触发的宽度 ⇒ 与输入框同宽同左缘，绝不会超出。壳本身不吃事件，
                      只有里面的箭头与状态点可点（事件从它们冒泡到触发器）。 */}
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <span className="pointer-events-none absolute inset-0 flex items-center justify-end gap-1 pr-3">
                        {dimensionState !== null && (
                          <Tooltip content={dimensionState.reason}>
                            <span
                              role="status"
                              aria-label={dimensionState.reason}
                              data-slot="dimension-status"
                              data-state={dimensionState.state}
                              className={cn(
                                "pointer-events-auto inline-block size-2 rounded-full",
                                dimensionState.state === "probing"
                                  ? "bg-muted-foreground/40 animate-pulse"
                                  : "bg-muted-foreground/40",
                              )}
                            />
                          </Tooltip>
                        )}
                        {dimensionTiers.length > 0 && (
                          <button
                            type="button"
                            aria-label={F.dimensionTierHint}
                            data-slot="dimension-tiers-trigger"
                            className="text-muted-foreground hover:text-foreground pointer-events-auto inline-flex"
                          >
                            <ChevronDown className="size-4 opacity-50" />
                          </button>
                        )}
                      </span>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent
                      align="start"
                      className="w-(--radix-dropdown-menu-trigger-width) min-w-0"
                    >
                      {dimensionVerdict?.native != null && (
                        <DropdownMenuLabel className="text-muted-foreground font-normal">
                          {F.dimensionNativeHint(dimensionVerdict.native)}
                        </DropdownMenuLabel>
                      )}
                      <DropdownMenuSeparator />
                      <DropdownMenuLabel className="text-muted-foreground font-normal">
                        {F.dimensionTierHint}
                      </DropdownMenuLabel>
                      {dimensionTiers.map((width) => (
                        <DropdownMenuItem
                          key={width}
                          data-slot="dimension-tier"
                          onSelect={() => update("embedding_dimension", String(width))}
                        >
                          {width}
                        </DropdownMenuItem>
                      ))}
                    </DropdownMenuContent>
                  </DropdownMenu>
                </div>
              </div>
              <div className={ROW}>
                <RowLabel info={`${F.sparseSourceHint} ${F.sparseProbeHint}`}>
                  {F.embeddingSparseSource}
                </RowLabel>
                <OptionSelect
                  label={F.embeddingSparseSource}
                  value={values.embedding_sparse_source}
                  options={EMBEDDING_SPARSE_SOURCE_OPTIONS}
                  labels={SPARSE_SOURCE_LABELS}
                  disabledReasons={
                    isSparseProviderOptionDisabled(sparseCapability)
                      ? { provider: F.sparseProviderDenseOnly }
                      : undefined
                  }
                  // The probe's state rides in the field it is about (see `OptionSelect`): 检测中
                  // while the call is in flight, 未验证 once it came back without an answer. A
                  // known refusal says nothing here — it is already loud below the card and beside
                  // Save, and a third copy would be noise.
                  trailing={
                    probe.isPending ? (
                      <span role="status">{F.sparseProbing}</span>
                    ) : sparseUnverified ? (
                      <span>{F.sparseUnverified}</span>
                    ) : null
                  }
                  onChange={(next) =>
                    update(
                      "embedding_sparse_source",
                      next as RagConfigFormValues["embedding_sparse_source"],
                    )
                  }
                />
              </div>

              {sparseExternal ? (
                <>
                  {/* The sparse service is asked the same four questions, in the same order, as
                      the embedding service above — 提供商 / Model ID / API Key / 接口地址. The
                      gutter names them once for both; each control still carries its own
                      accessible name (F.sparse*) so the two are never confused out loud. */}
                  <div className={ROW}>
                    <RowLabel nested>{F.providerLabel}</RowLabel>
                    <OptionSelect
                      label={F.sparseProvider}
                      value={values.sparse_provider}
                      options={SPARSE_PROVIDER_OPTIONS}
                      labels={SPARSE_SERVICE_LABELS}
                      onChange={(next) =>
                        update(
                          "sparse_provider",
                          next as RagConfigFormValues["sparse_provider"],
                        )
                      }
                    />
                  </div>
                  <div className={ROW}>
                    <RowLabel nested info={F.sparseModelHint}>
                      {F.modelLabel}
                    </RowLabel>
                    <Input
                      value={values.sparse_model}
                      aria-label={F.sparseModel}
                      {...AUTOFILL_OFF_INPUT_PROPS}
                      onChange={(event) =>
                        update("sparse_model", event.target.value)
                      }
                    />
                  </div>
                  <div className={ROW}>
                    <RowLabel nested>{F.apiKeyLabel}</RowLabel>
                    <SecretInput
                      badge={
                        isEnvBacked("sparse_api_key")
                          ? F.secretFromEnvBadge
                          : undefined
                      }
                      value={values.sparse_api_key}
                      aria-label={F.sparseApiKey}
                      onChange={(event) =>
                        update("sparse_api_key", event.target.value)
                      }
                    />
                  </div>
                  <div className={ROW}>
                    <RowLabel nested>{F.endpointLabel}</RowLabel>
                    <div className="relative w-full min-w-0">
                      {/* The mark's room is reserved whether or not there is one, so the visible
                          address never reflows when a verdict lands. */}
                      <Input
                        className="pr-24"
                        value={values.sparse_base_url}
                        aria-label={F.sparseBaseUrl}
                        {...AUTOFILL_OFF_INPUT_PROPS}
                        onChange={(event) =>
                          update("sparse_base_url", event.target.value)
                        }
                      />
                      {sparseServiceStatus && (
                        <span
                          data-slot="sparse-service-status"
                          className={cn(
                            "pointer-events-none absolute top-1/2 right-3 -translate-y-1/2 text-xs",
                            sparseServiceStatus.tone,
                          )}
                        >
                          {sparseServiceStatus.text}
                        </span>
                      )}
                    </div>
                  </div>
                </>
              ) : (
                <>
                  {[
                    F.providerLabel,
                    F.modelLabel,
                    F.apiKeyLabel,
                    F.endpointLabel,
                  ].map((label) => (
                    <div key={label} className={ROW}>
                      <RowLabel nested>{label}</RowLabel>
                      <LockedBox reason={F.lockedExternalOnly} />
                    </div>
                  ))}
                </>
              )}
            </Rows>
          </CollapsibleContent>
        </Collapsible>

        {embeddingChanged && (
          <p className="text-destructive mt-3 text-xs" role="alert">
            {F.embeddingChangeWarning}
          </p>
        )}

        {/* Outside the disclosure on purpose: a warning nobody can see while the section is
            collapsed is not a warning. */}
        {sparseBlockReason && (
          <p className="text-destructive mt-3 text-xs" role="alert">
            {sparseBlockReason}
          </p>
        )}
      </Group>

      <Group title={F.groupExtraction} info={F.extractModelHint}>
        <div className={ROW}>
          <RowLabel>{F.extractModel}</RowLabel>
          <Select
            value={values.extract_model || MODEL_REFERENCE_NONE}
            onValueChange={(next) =>
              update("extract_model", next === MODEL_REFERENCE_NONE ? "" : next)
            }
          >
            <SelectTrigger
              className="w-full min-w-0"
              aria-label={F.extractModel}
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {modelReferenceOptions(
                models,
                values.extract_model,
                F.extractModelNone,
              ).map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className={ROW}>
          <RowLabel info={F.wikiModelHint}>{F.wikiModel}</RowLabel>
          <Select
            value={values.wiki_model || MODEL_REFERENCE_NONE}
            onValueChange={(next) =>
              update("wiki_model", next === MODEL_REFERENCE_NONE ? "" : next)
            }
          >
            <SelectTrigger
              className="w-full min-w-0"
              aria-label={F.wikiModel}
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {modelReferenceOptions(
                models,
                values.wiki_model,
                F.wikiModelNone,
              ).map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </Group>

      <Group title={F.groupEvaluation} info={F.groupEvaluationHint}>
        <div className={ROW}>
          <RowLabel>{F.judgeModel}</RowLabel>
          <Select
            value={values.judge_model || MODEL_REFERENCE_NONE}
            onValueChange={(next) =>
              update("judge_model", next === MODEL_REFERENCE_NONE ? "" : next)
            }
          >
            <SelectTrigger className="w-full min-w-0" aria-label={F.judgeModel}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {modelReferenceOptions(
                models,
                values.judge_model,
                F.judgeModelNone,
              ).map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className={ROW}>
          <RowLabel info={F.synthesisModelHint}>{F.synthesisModel}</RowLabel>
          <Select
            value={values.synthesis_model || MODEL_REFERENCE_NONE}
            onValueChange={(next) =>
              update(
                "synthesis_model",
                next === MODEL_REFERENCE_NONE ? "" : next,
              )
            }
          >
            <SelectTrigger
              className="w-full min-w-0"
              aria-label={F.synthesisModel}
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {modelReferenceOptions(
                models,
                values.synthesis_model,
                F.synthesisModelNone,
              ).map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </Group>

      <Group title={F.groupMultimodal} info={F.groupMultimodalHint}>
        <Rows>
          <div className={ROW}>
            <RowLabel info={F.captionModelHint}>{F.captionModel}</RowLabel>
            <div className="space-y-1.5">
              <Select
                value={values.vlm_model || MODEL_REFERENCE_NONE}
                onValueChange={(next) =>
                  update("vlm_model", next === MODEL_REFERENCE_NONE ? "" : next)
                }
              >
                <SelectTrigger
                  className="w-full min-w-0"
                  aria-label={F.captionModel}
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {visionOptions.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>

              {!hasVisionModel && (
                <p className="text-muted-foreground text-xs">
                  {F.vlmNoVisionModel}
                </p>
              )}
            </div>
          </div>

          {/* 主角行（spec 2026-09-30 观感二轮）：与「图片描述模型 (VLM)」同级；它的细节
              （Model ID / API Key / 接口地址）缩进一级，照稀疏服务那套嵌套。
              手动探针零入口休眠（同日第三轮裁定）：兜底＝保存期构造拒绝（缺地址/钥匙 ⇒ 400）
              ＋ 入库期 asr=failed；探针链路与保存区那道门留着，只是没有可点的控件。 */}
          <div className={ROW}>
            <RowLabel>{F.asrModelRow}</RowLabel>
            <OptionSelect
              label={F.asrProvider}
              value={values.video.asr_provider}
              options={ASR_PROVIDER_OPTIONS}
              labels={{
                funasr: F.asrProviderFunasr,
                whisper: F.asrProviderWhisper,
                "openai-audio": F.asrProviderOpenaiAudio,
                dashscope: F.asrProviderDashscope,
              }}
              groups={ASR_PROVIDER_GROUPS.map((group) => ({
                labelKey: group.labelKey,
                label: F[group.labelKey],
                ids: group.ids,
              }))}
              onChange={(next) => {
                const provider =
                  next as RagConfigFormValues["video"]["asr_provider"];
                updateVideo("asr_provider", provider);
                // 切换即改值：另一个引擎跑不了的值换成目标引擎的首行（spec 2026-09-27 §2 D2）。
                // 服务档的模型名是服务侧的、没有候选行，所以那一侧不动值。
                const kept = asrModelForProviderSwitch(
                  provider,
                  values.video.asr_model,
                );
                if (kept !== values.video.asr_model)
                  updateVideo("asr_model", kept);
              }}
            />
          </div>

          <div className={ROW}>
            <RowLabel
              nested
              info={
                values.video.asr_provider === "whisper"
                  ? F.asrModelWhisperHint
                  : values.video.asr_provider === "funasr"
                    ? F.asrModelFunasrHint
                    : F.asrModelServiceHint
              }
            >
              {F.modelLabel}
            </RowLabel>
            {/* 与「维度」行同款：输入框自由填 + 框内下拉（候选组按引擎整组换）。
                服务档的模型名是服务侧的、没有候选清单，所以那一侧不给下拉。 */}
            <div className="relative w-full" data-slot="asr-model-control">
              <Input
                aria-label={F.asrModel}
                data-slot="asr-model-input"
                className={cn(
                  "w-full",
                  values.video.asr_provider !== "openai-audio" &&
                    values.video.asr_provider !== "dashscope" &&
                    "pr-10",
                )}
                value={values.video.asr_model}
                placeholder={
                  asrServiceApplies
                    ? ""
                    : ASR_MODEL_MENU[values.video.asr_provider][0]
                }
                onChange={(event) =>
                  updateVideo("asr_model", event.target.value)
                }
                {...AUTOFILL_OFF_INPUT_PROPS}
              />
              {asrServiceApplies ? null : (
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <span className="pointer-events-none absolute inset-0 flex items-center justify-end pr-3">
                      <button
                        type="button"
                        aria-label={F.asrModelCandidates}
                        data-slot="asr-model-candidates-trigger"
                        className="text-muted-foreground hover:text-foreground pointer-events-auto inline-flex"
                      >
                        <ChevronDown className="size-4 opacity-50" />
                      </button>
                    </span>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent
                    align="start"
                    className="w-(--radix-dropdown-menu-trigger-width) min-w-0"
                  >
                    <DropdownMenuLabel className="text-muted-foreground font-normal">
                      {F.asrModelCandidates}
                    </DropdownMenuLabel>
                    {ASR_MODEL_MENU[values.video.asr_provider].map((name) => (
                      <DropdownMenuItem
                        key={name}
                        data-slot="asr-model-candidate"
                        onSelect={() => updateVideo("asr_model", name)}
                      >
                        {name}
                      </DropdownMenuItem>
                    ))}
                  </DropdownMenuContent>
                </DropdownMenu>
              )}
            </div>
          </div>

          {/* 钥匙与地址：本地引擎（进程内）两格都锁——它们对进程内引擎没有概念；
              服务档两格都填，地址格用厂商端点做灰字占位（D3）。恒显、锁而不藏。 */}
          <div className={ROW}>
            <RowLabel nested>{F.apiKeyLabel}</RowLabel>
            {asrServiceApplies ? (
              <SecretInput
                badge={asrKeyPresent ? F.secretFromEnvBadge : undefined}
                value={values.asr_api_key}
                aria-label={F.asrApiKey}
                onChange={(event) => update("asr_api_key", event.target.value)}
              />
            ) : (
              <div data-slot="asr-locked">
                <LockedBox reason={F.lockedServiceOnly} />
              </div>
            )}
          </div>

          <div className={ROW}>
            <RowLabel nested>{F.endpointLabel}</RowLabel>
            {asrServiceApplies ? (
              <Input
                value={values.asr_base_url}
                aria-label={F.asrBaseUrl}
                placeholder={endpointPlaceholderFor(
                  view?.asr_providers,
                  values.video.asr_provider,
                )}
                onChange={(event) => update("asr_base_url", event.target.value)}
                {...AUTOFILL_OFF_INPUT_PROPS}
              />
            ) : (
              <div data-slot="asr-locked">
                <LockedBox reason={F.lockedServiceOnly} />
              </div>
            )}
          </div>
        </Rows>
      </Group>

      <Group title={F.groupServices} info={F.groupServicesHint}>
        <Rows>
          <div className={ROW}>
            <RowLabel>{F.qdrantUrl}</RowLabel>
            <Input
              type="url"
              value={values.qdrant_url}
              aria-label={F.qdrantUrl}
              {...AUTOFILL_OFF_INPUT_PROPS}
              onChange={(event) => update("qdrant_url", event.target.value)}
            />
          </div>

          <div className={ROW}>
            <RowLabel info={F.parseBaseUrlHint}>{F.parseProvider}</RowLabel>
            <OptionSelect
              label={F.parseProvider}
              value={values.parse_provider}
              options={PARSE_PROVIDER_OPTIONS}
              labels={PROVIDER_LABELS}
              onChange={(next) =>
                update(
                  "parse_provider",
                  next as RagConfigFormValues["parse_provider"],
                )
              }
            />
          </div>

          {values.parse_provider === "mineru-local" ? (
            <>
              <div className={ROW}>
                <RowLabel>{F.parseBaseUrl}</RowLabel>
                <Input
                  value={values.parse_base_url}
                  aria-label={F.parseBaseUrl}
                  {...AUTOFILL_OFF_INPUT_PROPS}
                  onChange={(event) =>
                    update("parse_base_url", event.target.value)
                  }
                />
              </div>
              <div className={ROW}>
                <RowLabel info={F.parseTierHint}>{F.parseTier}</RowLabel>
                <OptionSelect
                  label={F.parseTier}
                  value={values.parse_tier}
                  options={PARSE_TIER_OPTIONS}
                  labels={PROVIDER_LABELS}
                  onChange={(next) =>
                    update(
                      "parse_tier",
                      next as RagConfigFormValues["parse_tier"],
                    )
                  }
                />
              </div>
              <div className={ROW}>
                <RowLabel>{F.parseLanguage}</RowLabel>
                <LockedBox reason={F.lockedCloudOnly} />
              </div>
              <div className={ROW}>
                <RowLabel>{F.parseModelVersion}</RowLabel>
                <LockedBox reason={F.lockedCloudOnly} />
              </div>
              <div className={ROW}>
                <RowLabel>{F.mineruToken}</RowLabel>
                <LockedBox reason={F.lockedCloudOnly} />
              </div>
            </>
          ) : (
            <>
              <div className={ROW}>
                <RowLabel>{F.parseBaseUrl}</RowLabel>
                <Input
                  value={values.parse_base_url}
                  aria-label={F.parseBaseUrl}
                  // 灰字＝留空时的实际去向（官方端点，与后端 parser.MINERU_BASE_URL 同值）；
                  // 与 embedding/rerank 地址行的既有形状一致。本地分支没有默认值，不给占位
                  // （2026-09-30 交付后调整）。
                  placeholder="https://mineru.net"
                  {...AUTOFILL_OFF_INPUT_PROPS}
                  onChange={(event) =>
                    update("parse_base_url", event.target.value)
                  }
                />
              </div>
              <div className={ROW}>
                <RowLabel>{F.parseTier}</RowLabel>
                <LockedBox reason={F.lockedLocalOnly} />
              </div>
              <div className={ROW}>
                <RowLabel info={F.parseLanguageHint}>
                  {F.parseLanguage}
                </RowLabel>
                <OptionSelect
                  label={F.parseLanguage}
                  value={values.parse_language}
                  options={PARSE_LANGUAGE_OPTIONS}
                  labels={PARSE_LANGUAGE_LABELS}
                  onChange={(next) =>
                    update(
                      "parse_language",
                      next as RagConfigFormValues["parse_language"],
                    )
                  }
                />
              </div>
              <div className={ROW}>
                <RowLabel info={F.parseModelVersionHint}>
                  {F.parseModelVersion}
                </RowLabel>
                <OptionSelect
                  label={F.parseModelVersion}
                  value={values.parse_model_version}
                  options={PARSE_MODEL_VERSION_OPTIONS}
                  labels={PARSE_MODEL_VERSION_LABELS}
                  onChange={(next) =>
                    update(
                      "parse_model_version",
                      next as RagConfigFormValues["parse_model_version"],
                    )
                  }
                />
              </div>
              <div className={ROW}>
                <RowLabel>{F.mineruToken}</RowLabel>
                <SecretInput
                  badge={
                    isEnvBacked("mineru_api_token")
                      ? F.secretFromEnvBadge
                      : undefined
                  }
                  value={values.mineru_api_token}
                  aria-label={F.mineruToken}
                  onChange={(event) =>
                    update("mineru_api_token", event.target.value)
                  }
                />
              </div>
            </>
          )}
        </Rows>
      </Group>

      <Group title={F.reindexTitle} info={F.reindexHint}>
        <div className={ROW}>
          <RowLabel>{F.reindexKbLabel}</RowLabel>
          <Select value={reindexKbId} onValueChange={setReindexKbId}>
            <SelectTrigger
              className="w-full min-w-0"
              aria-label={F.reindexKbLabel}
            >
              <SelectValue placeholder={F.reindexKbPlaceholder} />
            </SelectTrigger>
            <SelectContent>
              {libraries.map((kb) => (
                <SelectItem key={kb.id} value={kb.id}>
                  {kb.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="mt-3 flex items-center justify-end gap-3">
          {reindexRunning && (
            <span className="text-muted-foreground text-xs" role="status">
              {reindexProgress
                ? `${F.reindexRunning} ${reindexProgress.documents_done}/${reindexProgress.documents_total} · ${F.reindexChunksWritten} ${reindexProgress.chunks_indexed + reindexProgress.entities_indexed + reindexProgress.wiki_entries_indexed + reindexProgress.cards_indexed}`
                : F.reindexRunning}
            </span>
          )}
          {!reindexRunning && reindexStatus.data?.last_run === "succeeded" && (
            <span className="text-muted-foreground text-xs">
              {F.reindexLastSucceeded}
            </span>
          )}
          {!reindexRunning && reindexStatus.data?.last_run === "failed" && (
            <span className="text-destructive text-xs" role="alert">
              {F.reindexLastFailed}
            </span>
          )}
          {libraries.length === 0 && (
            <span className="text-muted-foreground text-xs">
              {F.reindexNoKb}
            </span>
          )}
          <Button
            variant="outline"
            disabled={!reindexKbId || reindexRunning}
            onClick={() => setReindexOpen(true)}
          >
            {F.reindexAction}
          </Button>
        </div>
      </Group>

      <ReindexDialog
        open={reindexOpen}
        onOpenChange={setReindexOpen}
        kbName={selectedKb?.name ?? ""}
        onConfirm={handleReindexConfirm}
        pending={reindex.isPending}
      />

      <DimensionMigrationDialog
        open={dimensionConfirmOpen}
        onOpenChange={setDimensionConfirmOpen}
        onConfirm={handleDimensionConfirm}
        pending={save.isPending}
      />

      {/* A save that *went through* with a caveat — not the alert slot, and not a toast to
          dismiss: it says what the server could not check about the configuration now in force. */}
      {saveWarning && (
        <p className="text-muted-foreground mt-3 text-sm" role="status">
          {saveWarning}
        </p>
      )}

      {/* The width migration outlives the save that started it: the row keeps showing the width
          in force, and this line is where the admin learns when the switch actually happened. */}
      {migration.data && (
        <p
          className={cn(
            "mt-3 text-sm",
            migration.data.state === "failed"
              ? "text-destructive"
              : "text-muted-foreground",
          )}
          role="status"
          data-slot="migration-status"
        >
          {migrationRunning
            ? `${F.migrationRunning} ${migrationProgress ? `${migrationProgress.kbs_done}/${migrationProgress.kbs_total}` : ""}`
            : migration.data.state === "succeeded"
              ? F.migrationSucceeded
              : `${F.migrationFailed}${migration.data.detail ?? ""}`}
        </p>
      )}

      <div className="flex items-center justify-end gap-3">
        {/* Disabled without a reason reads as a broken button, and the alert above can be
            scrolled out of sight — so the same sentence rides next to the button it blocks. */}
        {migrationRunning ? (
          <span className="text-muted-foreground text-xs">
            {F.migrationRunning}
          </span>
        ) : saveBlockReason ? (
          <span className="text-destructive text-xs">{saveBlockReason}</span>
        ) : (
          !hasChanges && (
            <span className="text-muted-foreground text-xs">{F.noChanges}</span>
          )
        )}
        <Button
          onClick={handleSave}
          disabled={
            !hasChanges ||
            Boolean(saveBlockReason) ||
            save.isPending ||
            migrationRunning
          }
        >
          {save.isPending ? t.common.loading : t.common.save}
        </Button>
      </div>
    </div>
  );
}

/** A titled card whose explanatory sentence sits behind an ⓘ (see `InfoTip`). */
function Group({
  title,
  info,
  children,
}: {
  title: string;
  info?: string;
  children: React.ReactNode;
}) {
  return (
    <Card className="gap-3 py-4">
      <CardHeader className="px-4">
        <CardTitle className="flex items-center gap-1.5 text-sm">
          {title}
          {info && <InfoTip text={info} />}
        </CardTitle>
      </CardHeader>
      <CardContent className="px-4">{children}</CardContent>
    </Card>
  );
}
