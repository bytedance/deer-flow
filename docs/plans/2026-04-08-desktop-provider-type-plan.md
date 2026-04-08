# Desktop Provider Type Selection — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the hardcoded 3-provider desktop settings with a vendor-based provider type selector, empty default list, and dynamic config.yaml models generation.

**Architecture:** Frontend Add Provider Dialog selects vendor → auto-fills preset values → saves to DesktopSettings → Desktop main process generates config.yaml models entries on runtime start → backend hot-reloads config.

**Tech Stack:** React (Next.js), Radix Select, Electron IPC, Node.js YAML generation, existing Desktop Bridge

---

### Task 1: Add PROVIDER_PRESETS constant and extend DesktopProviderSetting type (Desktop)

**Files:**
- Modify: `desktop/main/config.ts`

**Step 1: Define the PROVIDER_PRESETS map and extended type**

Add `providerType`, `defaultModel` fields to `DesktopProviderSetting`. Add a `PROVIDER_PRESETS` constant mapping each vendor to its preset values. Change `DEFAULT_DESKTOP_SETTINGS.providers` to `[]`.

```typescript
// desktop/main/config.ts

export type DesktopProviderSetting = {
  id: string;
  providerType: string;
  label: string;
  apiKeyEnv: string;
  baseUrl: string;
  defaultModel: string;
};

export type ProviderPreset = {
  label: string;
  apiKeyEnv: string;
  use: string;
  baseUrl: string;
  defaultModel: string;
  apiKeyField?: string;  // override for non-standard key field names (e.g. gemini_api_key)
};

export const PROVIDER_PRESETS: Record<string, ProviderPreset> = {
  openai: {
    label: "OpenAI",
    apiKeyEnv: "OPENAI_API_KEY",
    use: "langchain_openai:ChatOpenAI",
    baseUrl: "",
    defaultModel: "gpt-4o",
  },
  anthropic: {
    label: "Anthropic",
    apiKeyEnv: "ANTHROPIC_API_KEY",
    use: "langchain_anthropic:ChatAnthropic",
    baseUrl: "",
    defaultModel: "claude-sonnet-4-20250514",
  },
  google: {
    label: "Google Gemini",
    apiKeyEnv: "GEMINI_API_KEY",
    use: "langchain_google_genai:ChatGoogleGenerativeAI",
    baseUrl: "",
    defaultModel: "gemini-2.5-pro",
    apiKeyField: "gemini_api_key",
  },
  deepseek: {
    label: "DeepSeek",
    apiKeyEnv: "DEEPSEEK_API_KEY",
    use: "deerflow.models.patched_deepseek:PatchedChatDeepSeek",
    baseUrl: "https://api.deepseek.com/v1",
    defaultModel: "deepseek-chat",
  },
  volcengine: {
    label: "Volcengine (Doubao)",
    apiKeyEnv: "VOLCENGINE_API_KEY",
    use: "deerflow.models.patched_deepseek:PatchedChatDeepSeek",
    baseUrl: "https://ark.cn-beijing.volces.com/api/v3",
    defaultModel: "doubao-seed-1-8-251228",
  },
  moonshot: {
    label: "Moonshot (Kimi)",
    apiKeyEnv: "MOONSHOT_API_KEY",
    use: "deerflow.models.patched_deepseek:PatchedChatDeepSeek",
    baseUrl: "https://api.moonshot.cn/v1",
    defaultModel: "kimi-k2.5",
  },
  minimax: {
    label: "MiniMax",
    apiKeyEnv: "MINIMAX_API_KEY",
    use: "langchain_openai:ChatOpenAI",
    baseUrl: "https://api.minimax.io/v1",
    defaultModel: "MiniMax-M2.5",
  },
  openrouter: {
    label: "OpenRouter",
    apiKeyEnv: "OPENROUTER_API_KEY",
    use: "langchain_openai:ChatOpenAI",
    baseUrl: "https://openrouter.ai/api/v1",
    defaultModel: "",
  },
  novita: {
    label: "Novita AI",
    apiKeyEnv: "NOVITA_API_KEY",
    use: "langchain_openai:ChatOpenAI",
    baseUrl: "https://api.novita.ai/openai",
    defaultModel: "",
  },
  "openai-compatible": {
    label: "OpenAI-Compatible",
    apiKeyEnv: "",
    use: "langchain_openai:ChatOpenAI",
    baseUrl: "",
    defaultModel: "",
  },
};

const DEFAULT_DESKTOP_SETTINGS: DesktopSettings = {
  defaultModel: null,
  providers: [],
};
```

**Step 2: Verify desktop builds**

Run: `cd desktop && npm run build` (or `npx tsc --noEmit`)
Expected: No type errors

**Step 3: Commit**

```bash
git add desktop/main/config.ts
git commit -m "feat(desktop): add PROVIDER_PRESETS and extend DesktopProviderSetting type"
```

---

### Task 2: Generate models config on runtime start (Desktop)

**Files:**
- Modify: `desktop/main/processes.ts`
- Modify: `desktop/main/paths.ts`

**Step 1: Add desktopModelsConfigPath to paths**

In `desktop/main/paths.ts`, add `desktopModelsConfigPath` to `DesktopPaths`:

```typescript
// In DesktopPaths type:
desktopModelsConfigPath: string;

// In getDesktopPaths return:
desktopModelsConfigPath: path.join(runtimeDir, "desktop-models.yaml"),
```

**Step 2: Generate models YAML in processes.ts start()**

Before spawning the child process, generate a `desktop-models.yaml` from providers settings and point `DEER_FLOW_CONFIG_PATH` to a merged config, or write models entries directly.

Strategy: read the existing `config.yaml`, replace the `models:` field with generated entries, write to `runtimeDir/config.yaml`, and use that as `DEER_FLOW_CONFIG_PATH`.

```typescript
// desktop/main/processes.ts — add imports
import fs from "node:fs/promises";
import { PROVIDER_PRESETS, type DesktopProviderSetting } from "./config.js";

// Add helper function:
function generateModelEntry(provider: DesktopProviderSetting) {
  const preset = PROVIDER_PRESETS[provider.providerType];
  const use = preset?.use ?? "langchain_openai:ChatOpenAI";
  const apiKeyField = preset?.apiKeyField ?? "api_key";

  const entry: Record<string, unknown> = {
    name: provider.defaultModel || provider.id,
    display_name: `${provider.label} - ${provider.defaultModel || "default"}`,
    use,
    model: provider.defaultModel,
    [apiKeyField]: `$${provider.apiKeyEnv}`,
    request_timeout: 600.0,
    max_retries: 2,
  };

  if (provider.baseUrl) {
    const baseUrlField = use.includes("patched_deepseek") ? "api_base" : "base_url";
    entry[baseUrlField] = provider.baseUrl;
  }

  return entry;
}

async function generateRuntimeConfig(
  repoConfigPath: string,
  runtimeConfigPath: string,
  providers: DesktopProviderSetting[],
) {
  let configContent = await fs.readFile(repoConfigPath, "utf8");

  const modelEntries = providers
    .filter((p) => p.defaultModel)
    .map(generateModelEntry);

  // Replace the models: [] line with generated entries
  // Simple YAML serialization for model entries
  const modelsYaml = modelEntries.length === 0
    ? "models: []"
    : "models:\n" + modelEntries.map((entry) => {
        const lines = Object.entries(entry)
          .map(([key, value]) => {
            if (typeof value === "string") return `    ${key}: ${value.startsWith("$") ? value : JSON.stringify(value)}`;
            return `    ${key}: ${value}`;
          })
          .join("\n");
        return `  - ${lines.trimStart().replace(/^    /, "")}`;
      }).join("\n");

  // Replace models: [] or models: section
  configContent = configContent.replace(
    /^models:\s*\[\].*?(?=\n\S|\n#\s*=)/ms,
    modelsYaml + "\n",
  );

  await fs.writeFile(runtimeConfigPath, configContent, "utf8");
}
```

In `start()`, add before the `spawn` call:

```typescript
const runtimeConfigPath = path.join(options.paths.runtimeDir, "config.yaml");
await generateRuntimeConfig(
  options.paths.repoConfigPath,
  runtimeConfigPath,
  settings.providers,
);

// Update env to use runtime config
const env = {
  ...process.env,
  DEER_DESKTOP: "1",
  DEER_FLOW_CONFIG_PATH: runtimeConfigPath,  // changed from repoConfigPath
  // ... rest unchanged
};
```

**Step 3: Verify desktop builds**

Run: `cd desktop && npx tsc --noEmit`
Expected: No type errors

**Step 4: Commit**

```bash
git add desktop/main/processes.ts desktop/main/paths.ts
git commit -m "feat(desktop): generate runtime config.yaml models from provider settings"
```

---

### Task 3: Mirror type changes in frontend (types only)

**Files:**
- Modify: `frontend/src/components/workspace/settings/model-settings-page.tsx` (types section only)

**Step 1: Update DesktopProviderSetting and add PROVIDER_PRESETS in frontend**

At the top of `model-settings-page.tsx`, update the `DesktopProviderSetting` type and add a frontend copy of presets:

```typescript
type DesktopProviderSetting = {
  id: string;
  providerType: string;
  label: string;
  apiKeyEnv: string;
  baseUrl: string;
  defaultModel: string;
};

type ProviderPreset = {
  label: string;
  apiKeyEnv: string;
  baseUrl: string;
  defaultModel: string;
};

const PROVIDER_PRESETS: Record<string, ProviderPreset> = {
  openai: { label: "OpenAI", apiKeyEnv: "OPENAI_API_KEY", baseUrl: "", defaultModel: "gpt-4o" },
  anthropic: { label: "Anthropic", apiKeyEnv: "ANTHROPIC_API_KEY", baseUrl: "", defaultModel: "claude-sonnet-4-20250514" },
  google: { label: "Google Gemini", apiKeyEnv: "GEMINI_API_KEY", baseUrl: "", defaultModel: "gemini-2.5-pro" },
  deepseek: { label: "DeepSeek", apiKeyEnv: "DEEPSEEK_API_KEY", baseUrl: "https://api.deepseek.com/v1", defaultModel: "deepseek-chat" },
  volcengine: { label: "Volcengine (Doubao)", apiKeyEnv: "VOLCENGINE_API_KEY", baseUrl: "https://ark.cn-beijing.volces.com/api/v3", defaultModel: "doubao-seed-1-8-251228" },
  moonshot: { label: "Moonshot (Kimi)", apiKeyEnv: "MOONSHOT_API_KEY", baseUrl: "https://api.moonshot.cn/v1", defaultModel: "kimi-k2.5" },
  minimax: { label: "MiniMax", apiKeyEnv: "MINIMAX_API_KEY", baseUrl: "https://api.minimax.io/v1", defaultModel: "MiniMax-M2.5" },
  openrouter: { label: "OpenRouter", apiKeyEnv: "OPENROUTER_API_KEY", baseUrl: "https://openrouter.ai/api/v1", defaultModel: "" },
  novita: { label: "Novita AI", apiKeyEnv: "NOVITA_API_KEY", baseUrl: "https://api.novita.ai/openai", defaultModel: "" },
  "openai-compatible": { label: "OpenAI-Compatible", apiKeyEnv: "", baseUrl: "", defaultModel: "" },
};

const PROVIDER_TYPE_OPTIONS = Object.entries(PROVIDER_PRESETS).map(([key, preset]) => ({
  value: key,
  label: preset.label,
}));
```

Remove the old `EMPTY_PROVIDER` constant.

**Step 2: Commit**

```bash
git add frontend/src/components/workspace/settings/model-settings-page.tsx
git commit -m "feat(frontend): mirror DesktopProviderSetting type changes and add PROVIDER_PRESETS"
```

---

### Task 4: Add i18n keys for provider dialog

**Files:**
- Modify: `frontend/src/core/i18n/locales/types.ts` (settings.models section)
- Modify: `frontend/src/core/i18n/locales/en-US.ts`
- Modify: `frontend/src/core/i18n/locales/zh-CN.ts`

**Step 1: Add new keys to types.ts**

In `settings.models` section of `Translations`, add:

```typescript
models: {
  // ... existing keys ...
  providerType: string;
  providerTypePlaceholder: string;
  providerName: string;
  modelName: string;
  modelNamePlaceholder: string;
  addProviderDialogTitle: string;
  addProviderDialogDescription: string;
  openaiCompatible: string;
  emptyProviders: string;
  emptyProvidersDescription: string;
};
```

**Step 2: Add English translations to en-US.ts**

```typescript
providerType: "Provider Type",
providerTypePlaceholder: "Select a provider",
providerName: "Provider Name",
modelName: "Model Name",
modelNamePlaceholder: "e.g. gpt-4o, claude-3-5-sonnet",
addProviderDialogTitle: "Add Model Provider",
addProviderDialogDescription: "Configure provider credentials.",
openaiCompatible: "OpenAI-Compatible",
emptyProviders: "No providers configured",
emptyProvidersDescription: "Add a provider to get started with AI models.",
```

**Step 3: Add Chinese translations to zh-CN.ts**

```typescript
providerType: "Provider 类型",
providerTypePlaceholder: "选择 Provider",
providerName: "Provider 名称",
modelName: "模型名称",
modelNamePlaceholder: "例如 gpt-4o, claude-3-5-sonnet",
addProviderDialogTitle: "添加模型 Provider",
addProviderDialogDescription: "配置 Provider 凭据。",
openaiCompatible: "OpenAI 兼容",
emptyProviders: "尚未配置 Provider",
emptyProvidersDescription: "添加一个 Provider 以开始使用 AI 模型。",
```

**Step 4: Commit**

```bash
git add frontend/src/core/i18n/locales/types.ts frontend/src/core/i18n/locales/en-US.ts frontend/src/core/i18n/locales/zh-CN.ts
git commit -m "feat(i18n): add provider type dialog translation keys"
```

---

### Task 5: Rewrite model-settings-page.tsx — Add Provider Dialog + empty state

**Files:**
- Modify: `frontend/src/components/workspace/settings/model-settings-page.tsx`

**Step 1: Add imports for Select and Label components**

```typescript
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
```

**Step 2: Add state for Add Provider Dialog**

Inside `ModelSettingsPage`, add:

```typescript
const [addDialogOpen, setAddDialogOpen] = useState(false);
const [newProviderType, setNewProviderType] = useState("");
const [newApiKey, setNewApiKey] = useState("");
const [newProviderName, setNewProviderName] = useState("");
const [newBaseUrl, setNewBaseUrl] = useState("");
const [newModelName, setNewModelName] = useState("");

const isOpenAICompatible = newProviderType === "openai-compatible";
const selectedPreset = newProviderType ? PROVIDER_PRESETS[newProviderType] : null;

const existingProviderTypes = new Set(providers.map((p) => p.providerType));

function resetAddDialog() {
  setNewProviderType("");
  setNewApiKey("");
  setNewProviderName("");
  setNewBaseUrl("");
  setNewModelName("");
  setAddDialogOpen(false);
}

function handleProviderTypeChange(value: string) {
  setNewProviderType(value);
  const preset = PROVIDER_PRESETS[value];
  if (preset && value !== "openai-compatible") {
    setNewProviderName(preset.label);
    setNewModelName(preset.defaultModel);
    setNewBaseUrl(preset.baseUrl);
  } else {
    setNewProviderName("");
    setNewModelName("");
    setNewBaseUrl("");
  }
}

async function handleAddProvider() {
  const preset = PROVIDER_PRESETS[newProviderType];
  if (!preset) return;

  const id = isOpenAICompatible
    ? `openai-compatible-${Date.now()}`
    : newProviderType;

  const apiKeyEnv = isOpenAICompatible
    ? `CUSTOM_${id.toUpperCase().replace(/-/g, "_")}_API_KEY`
    : preset.apiKeyEnv;

  const newProvider: DesktopProviderSetting = {
    id,
    providerType: newProviderType,
    label: newProviderName || preset.label,
    apiKeyEnv,
    baseUrl: isOpenAICompatible ? newBaseUrl : preset.baseUrl,
    defaultModel: newModelName || preset.defaultModel,
  };

  const nextProviders = [...providers, newProvider];
  await persistProviders(nextProviders);

  if (newApiKey.trim()) {
    await bridge?.saveSecret?.(apiKeyEnv, newApiKey.trim());
    setSecretStatuses((current) => ({ ...current, [apiKeyEnv]: true }));
  }

  resetAddDialog();
}
```

**Step 3: Replace addProvider button onClick**

Change the "+" button from `onClick={() => void addProvider()}` to `onClick={() => setAddDialogOpen(true)}`.

**Step 4: Add empty state when no providers**

Inside the providers list area, before the `.map()`:

```tsx
{providers.length === 0 && (
  <div className="flex flex-col items-center justify-center py-12 text-center">
    <KeyRoundIcon className="text-muted-foreground mb-4 size-10" />
    <div className="text-muted-foreground text-sm">{t.settings.models.emptyProviders}</div>
    <div className="text-muted-foreground mt-1 text-xs">{t.settings.models.emptyProvidersDescription}</div>
  </div>
)}
```

**Step 5: Add the Add Provider Dialog JSX**

After the existing delete confirmation Dialog:

```tsx
<Dialog open={addDialogOpen} onOpenChange={(open) => { if (!open) resetAddDialog(); }}>
  <DialogContent className="rounded-2xl">
    <DialogHeader className="text-left">
      <DialogTitle>{t.settings.models.addProviderDialogTitle}</DialogTitle>
      <DialogDescription>{t.settings.models.addProviderDialogDescription}</DialogDescription>
    </DialogHeader>
    <div className="space-y-4">
      <div className="space-y-2">
        <Label>{t.settings.models.providerType}</Label>
        <Select value={newProviderType} onValueChange={handleProviderTypeChange}>
          <SelectTrigger>
            <SelectValue placeholder={t.settings.models.providerTypePlaceholder} />
          </SelectTrigger>
          <SelectContent>
            {PROVIDER_TYPE_OPTIONS.map((option) => (
              <SelectItem
                key={option.value}
                value={option.value}
                disabled={option.value !== "openai-compatible" && existingProviderTypes.has(option.value)}
              >
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {isOpenAICompatible && (
        <div className="space-y-2">
          <Label>{t.settings.models.providerName}</Label>
          <Input
            value={newProviderName}
            placeholder={t.settings.models.providerNamePlaceholder}
            onChange={(e) => setNewProviderName(e.target.value)}
          />
        </div>
      )}

      {isOpenAICompatible && (
        <div className="space-y-2">
          <Label>{t.settings.models.baseUrl}</Label>
          <Input
            value={newBaseUrl}
            placeholder={t.settings.models.baseUrlPlaceholder}
            onChange={(e) => setNewBaseUrl(e.target.value)}
          />
        </div>
      )}

      {newProviderType && (
        <div className="space-y-2">
          <Label>{t.settings.models.apiKeyPlaceholder}</Label>
          <Input
            type="password"
            value={newApiKey}
            placeholder={t.settings.models.apiKeyPlaceholder}
            onChange={(e) => setNewApiKey(e.target.value)}
          />
        </div>
      )}

      {(isOpenAICompatible || (selectedPreset && !selectedPreset.defaultModel)) && (
        <div className="space-y-2">
          <Label>{t.settings.models.modelName}</Label>
          <Input
            value={newModelName}
            placeholder={t.settings.models.modelNamePlaceholder}
            onChange={(e) => setNewModelName(e.target.value)}
          />
        </div>
      )}

      {selectedPreset?.defaultModel && !isOpenAICompatible && (
        <div className="space-y-2">
          <Label>{t.settings.models.modelName}</Label>
          <Input
            value={newModelName}
            placeholder={selectedPreset.defaultModel}
            onChange={(e) => setNewModelName(e.target.value)}
          />
        </div>
      )}
    </div>
    <DialogFooter>
      <Button variant="outline" className="rounded-full px-5" onClick={resetAddDialog}>
        {t.common.cancel}
      </Button>
      <Button
        className="rounded-full px-5"
        disabled={!newProviderType || (isOpenAICompatible && (!newBaseUrl || !newModelName))}
        onClick={() => void handleAddProvider()}
      >
        {t.settings.models.addProvider}
      </Button>
    </DialogFooter>
  </DialogContent>
</Dialog>
```

**Step 6: Remove old addProvider function**

Delete the old `addProvider()` function and the old `updateProvider` / `saveProvider` / `saveSecret` functions that are no longer needed.

**Step 7: Verify frontend builds**

Run: `cd frontend && npx next lint && npx tsc --noEmit`
Expected: No errors

**Step 8: Commit**

```bash
git add frontend/src/components/workspace/settings/model-settings-page.tsx
git commit -m "feat(frontend): rewrite model settings with Add Provider Dialog and vendor presets"
```

---

### Task 6: End-to-end verification

**Step 1: Verify full frontend build**

Run: `cd frontend && npm run build`
Expected: Build succeeds

**Step 2: Verify desktop build (if applicable)**

Run: `cd desktop && npm run build`
Expected: Build succeeds

**Step 3: Final commit**

```bash
git add -A
git commit -m "feat: complete desktop provider type selection feature"
```
