import type { Model } from "./types";

export type ProviderModality = "text" | "image" | "video" | "audio";

export type ProviderMeta = {
  key: string;
  label: string;
  shortLabel: string;
  homepage?: string;
  accentClass: string;
  defaultModalities: ProviderModality[];
};

export type ProviderGroup = ProviderMeta & {
  models: Model[];
  configuredModalities: ProviderModality[];
};

const PROVIDER_CATALOG: Record<string, ProviderMeta> = {
  relay: {
    key: "relay",
    label: "Relay Gateway",
    shortLabel: "RG",
    accentClass: "bg-slate-100 text-slate-700",
    defaultModalities: ["text"],
  },
  bltcy: {
    key: "bltcy",
    label: "柏拉图AI",
    shortLabel: "柏",
    homepage: "https://api.bltcy.ai/",
    accentClass: "bg-sky-100 text-sky-700",
    defaultModalities: ["text", "image", "audio", "video"],
  },
  openai: {
    key: "openai",
    label: "OpenAI",
    shortLabel: "OA",
    homepage: "https://platform.openai.com",
    accentClass: "bg-emerald-100 text-emerald-700",
    defaultModalities: ["text", "image", "audio", "video"],
  },
  anthropic: {
    key: "anthropic",
    label: "Anthropic",
    shortLabel: "AN",
    homepage: "https://console.anthropic.com",
    accentClass: "bg-amber-100 text-amber-700",
    defaultModalities: ["text", "image", "audio"],
  },
  google: {
    key: "google",
    label: "Google",
    shortLabel: "GO",
    homepage: "https://ai.google.dev",
    accentClass: "bg-blue-100 text-blue-700",
    defaultModalities: ["text", "image", "audio", "video"],
  },
  deepseek: {
    key: "deepseek",
    label: "DeepSeek",
    shortLabel: "DS",
    homepage: "https://platform.deepseek.com",
    accentClass: "bg-indigo-100 text-indigo-700",
    defaultModalities: ["text", "image"],
  },
  volcengine: {
    key: "volcengine",
    label: "Volcengine",
    shortLabel: "VC",
    homepage: "https://www.volcengine.com",
    accentClass: "bg-orange-100 text-orange-700",
    defaultModalities: ["text", "image", "audio", "video"],
  },
  moonshot: {
    key: "moonshot",
    label: "Moonshot",
    shortLabel: "MS",
    homepage: "https://platform.moonshot.cn",
    accentClass: "bg-violet-100 text-violet-700",
    defaultModalities: ["text", "image", "audio"],
  },
  alibaba: {
    key: "alibaba",
    label: "Alibaba Cloud",
    shortLabel: "AB",
    homepage: "https://dashscope.aliyun.com",
    accentClass: "bg-yellow-100 text-yellow-700",
    defaultModalities: ["text", "image", "audio", "video"],
  },
  xai: {
    key: "xai",
    label: "xAI",
    shortLabel: "xA",
    homepage: "https://console.x.ai",
    accentClass: "bg-neutral-200 text-neutral-700",
    defaultModalities: ["text", "image", "audio", "video"],
  },
  zhipuai: {
    key: "zhipuai",
    label: "Zhipu AI",
    shortLabel: "ZP",
    homepage: "https://open.bigmodel.cn",
    accentClass: "bg-cyan-100 text-cyan-700",
    defaultModalities: ["text", "image", "video"],
  },
  unknown: {
    key: "unknown",
    label: "Unknown Provider",
    shortLabel: "UN",
    accentClass: "bg-muted text-muted-foreground",
    defaultModalities: ["text"],
  },
};

const UNKNOWN_PROVIDER_META: ProviderMeta = {
  key: "unknown",
  label: "Unknown Provider",
  shortLabel: "UN",
  accentClass: "bg-muted text-muted-foreground",
  defaultModalities: ["text"],
};

const PROVIDER_ALIASES: Record<string, string> = {
  "api.bltcy.ai": "bltcy",
  bltcy_ai: "bltcy",
  moonshotai: "moonshot",
  moonshotai_cn: "moonshot",
  zhipu: "zhipuai",
  zhipu_ai: "zhipuai",
  google_vertex: "google",
  google_vertex_anthropic: "anthropic",
};

const MODALITY_ORDER: ProviderModality[] = ["text", "image", "video", "audio"];

function normalizeProvider(value?: string | null): string {
  if (!value) {
    return "unknown";
  }
  const normalized = value.toLowerCase().trim().replace(/[\s-]+/g, "_");
  return PROVIDER_ALIASES[normalized] ?? normalized;
}

function inferProviderFromModel(model: Model): string {
  const candidates = [model.provider, model.name, model.model];

  for (const candidate of candidates) {
    const normalized = normalizeProvider(candidate);
    if (normalized in PROVIDER_CATALOG) {
      return normalized;
    }
    const raw = candidate?.toLowerCase() ?? "";
    if (raw.includes("gpt") || raw.includes("o3") || raw.includes("o4")) {
      return "openai";
    }
    if (raw.includes("claude")) {
      return "anthropic";
    }
    if (raw.includes("gemini")) {
      return "google";
    }
    if (raw.includes("deepseek")) {
      return "deepseek";
    }
    if (raw.includes("doubao")) {
      return "volcengine";
    }
    if (raw.includes("kimi") || raw.includes("moonshot")) {
      return "moonshot";
    }
    if (raw.includes("qwen")) {
      return "alibaba";
    }
    if (raw.includes("grok")) {
      return "xai";
    }
    if (raw.includes("glm")) {
      return "zhipuai";
    }
    if (raw.includes("relay")) {
      return "relay";
    }
  }

  return "unknown";
}

function normalizeModalities(values?: string[] | null): ProviderModality[] {
  const mapped = (values ?? [])
    .map((value) => value.toLowerCase().trim())
    .filter((value): value is ProviderModality =>
      MODALITY_ORDER.includes(value as ProviderModality),
    );

  return mapped.length > 0 ? Array.from(new Set(mapped)) : ["text"];
}

export function getProviderMeta(model: Model): ProviderMeta {
  const inferredKey = inferProviderFromModel(model);
  const baseMeta = PROVIDER_CATALOG[inferredKey] ?? UNKNOWN_PROVIDER_META;

  return {
    ...baseMeta,
    label: model.provider_label ?? baseMeta.label,
    homepage: model.provider_url ?? baseMeta.homepage,
  };
}

export function groupModelsByProvider(models: Model[]): ProviderGroup[] {
  const grouped = new Map<string, ProviderGroup>();

  for (const model of models) {
    const providerMeta = getProviderMeta(model);
    const existing = grouped.get(providerMeta.key);
    const configuredModalities = normalizeModalities(model.modalities);

    if (!existing) {
      grouped.set(providerMeta.key, {
        ...providerMeta,
        models: [model],
        configuredModalities,
      });
      continue;
    }

    existing.models.push(model);
    existing.configuredModalities = Array.from(
      new Set([...existing.configuredModalities, ...configuredModalities]),
    ).sort((left, right) => MODALITY_ORDER.indexOf(left) - MODALITY_ORDER.indexOf(right));
  }

  return Array.from(grouped.values())
    .map((group) => ({
      ...group,
      models: [...group.models].sort((left, right) =>
        (left.display_name ?? left.name).localeCompare(
          right.display_name ?? right.name,
        ),
      ),
    }))
    .sort((left, right) => left.label.localeCompare(right.label));
}

export function groupProviderModelsByFamily(models: Model[]) {
  const groups = new Map<string, Model[]>();

  for (const model of models) {
    const family =
      model.model.split("/")[0]?.split("-")[0]?.trim() ??
      model.name.split("-")[0]?.trim() ??
      "other";
    const familyLabel = family.length <= 4 ? family.toUpperCase() : capitalize(family);
    groups.set(familyLabel, [...(groups.get(familyLabel) ?? []), model]);
  }

  return Array.from(groups.entries())
    .map(([family, familyModels]) => ({
      family,
      models: familyModels.sort((left, right) =>
        (left.display_name ?? left.name).localeCompare(right.display_name ?? right.name),
      ),
    }))
    .sort((left, right) => left.family.localeCompare(right.family));
}

function capitalize(value: string) {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

export const providerModalityOrder = MODALITY_ORDER;
