# Desktop Provider Type 选择设计

## 背景

当前 Desktop App 内置 3 个固定 Provider（OpenAI / Anthropic / DeepSeek），用户无法选择类型，且存在多余的输入框（baseUrl / apiKeyEnv）。需要重新设计为：

- 默认 providers 为空列表
- 点击"添加 Provider"时弹出 Dialog，按厂商选择 Provider Type
- 除 OpenAI-Compatible 外，其他厂商只需输入 API Key
- OpenAI-Compatible 需额外填写 Base URL 和 Model Name
- 根据 providers 配置动态生成后端所需的 models 配置（config.yaml models 字段）

---

## 一、厂商预设表

| providerType | label | `apiKeyEnv` | `use` (后端) | 默认 `baseUrl` | 预设模型 |
|---|---|---|---|---|---|
| `openai` | OpenAI | `OPENAI_API_KEY` | `langchain_openai:ChatOpenAI` | _(空)_ | `gpt-4o` |
| `anthropic` | Anthropic | `ANTHROPIC_API_KEY` | `langchain_anthropic:ChatAnthropic` | _(空)_ | `claude-sonnet-4-20250514` |
| `google` | Google Gemini | `GEMINI_API_KEY` | `langchain_google_genai:ChatGoogleGenerativeAI` | _(空)_ | `gemini-2.5-pro` |
| `deepseek` | DeepSeek | `DEEPSEEK_API_KEY` | `deerflow.models.patched_deepseek:PatchedChatDeepSeek` | `https://api.deepseek.com/v1` | `deepseek-chat` |
| `volcengine` | Volcengine (Doubao) | `VOLCENGINE_API_KEY` | `deerflow.models.patched_deepseek:PatchedChatDeepSeek` | `https://ark.cn-beijing.volces.com/api/v3` | `doubao-seed-1-8-251228` |
| `moonshot` | Moonshot (Kimi) | `MOONSHOT_API_KEY` | `deerflow.models.patched_deepseek:PatchedChatDeepSeek` | `https://api.moonshot.cn/v1` | `kimi-k2.5` |
| `minimax` | MiniMax | `MINIMAX_API_KEY` | `langchain_openai:ChatOpenAI` | `https://api.minimax.io/v1` | `MiniMax-M2.5` |
| `openrouter` | OpenRouter | `OPENROUTER_API_KEY` | `langchain_openai:ChatOpenAI` | `https://openrouter.ai/api/v1` | _(用户填)_ |
| `novita` | Novita AI | `NOVITA_API_KEY` | `langchain_openai:ChatOpenAI` | `https://api.novita.ai/openai` | _(用户填)_ |
| `openai-compatible` | OpenAI-Compatible | _(用户填)_ | `langchain_openai:ChatOpenAI` | _(用户填)_ | _(用户填)_ |

---

## 二、前端设计

### 2.1 数据类型扩展

```typescript
// desktop/main/config.ts + frontend types
type DesktopProviderSetting = {
  id: string;           // 唯一 ID，格式: providerType 或 providerType-{timestamp}（custom）
  providerType: string; // 厂商标识，见预设表
  label: string;        // 显示名称，预设厂商自动填入，custom 用户填写
  apiKeyEnv: string;    // 环境变量名，预设厂商自动填入，custom 用户填写
  baseUrl: string;      // 仅 openai-compatible 时用户填写，其余预设填入或留空
  defaultModel: string; // 当前选中的默认模型名
};

type DesktopSettings = {
  defaultModel: string | null;
  providers: DesktopProviderSetting[];
};

// 默认值：空列表
const DEFAULT_DESKTOP_SETTINGS: DesktopSettings = {
  defaultModel: null,
  providers: [],
};
```

### 2.2 Add Provider Dialog 字段规则

**常规厂商（非 openai-compatible）：**

```
Provider Type *   [Select: OpenAI / Anthropic / Google / ...]
API Key *         [Password Input]
Default Model     [Select: 预设模型列表，可手动输入]
```

**OpenAI-Compatible（列表最后一项）：**

```
Provider Type *   [Select: OpenAI-Compatible]
Provider Name *   [Input: e.g. My Local LLM]
API Base URL *    [Input: e.g. http://localhost:8000/v1]
API Key           [Password Input]（可选）
Model Name *      [Input: e.g. qwen3-32b]
```

**交互细节：**
- 选择厂商后，`apiKeyEnv`、`baseUrl`、默认 `defaultModel` 自动从预设表填入
- `id` 生成规则：预设厂商用 `providerType`（唯一），openai-compatible 用 `openai-compatible-{timestamp}`（支持多个）
- 同一预设厂商只能添加一次（Select 中已添加的厂商置灰）
- 提交时立即调用 `bridge.saveSecret(apiKeyEnv, apiKey)` 保存 API Key
- 提交后调用 `bridge.updateDesktopSettings` 保存 provider 信息
- 提交后调用 `bridge.restartRuntime()` 重启后端进程使配置生效

### 2.3 Provider 卡片展示

```
Item (variant=outline)
├── ItemContent
│   ├── ItemTitle: [厂商图标] Provider Name
│   └── ItemDescription: [providerType badge] · 已配置 / 未配置
└── ItemActions
    ├── Switch (checked=configured, 关闭时 deleteSecret)
    └── Button (Trash icon, 删除 provider)
```

---

## 三、后端/Desktop 端设计

### 3.1 动态生成 config.yaml 的 models 字段

**位置：** `desktop/main/processes.ts` → `start()` 函数

在启动后端进程前，根据 `settings.providers` 生成 `models` 配置并写入 config.yaml（或单独的 `desktop-models.yaml` 文件，通过 `DEER_FLOW_EXTENSIONS_CONFIG_PATH` 引用）。

**YAML 生成逻辑（按 providerType 映射）：**

```typescript
function generateModelEntry(provider: DesktopProviderSetting): object {
  const base = {
    name: provider.defaultModel,
    display_name: `${provider.label} - ${provider.defaultModel}`,
    use: PROVIDER_PRESETS[provider.providerType].use,
    model: provider.defaultModel,
    api_key: `$${provider.apiKeyEnv}`,
    request_timeout: 600.0,
    max_retries: 2,
  };
  if (provider.baseUrl) {
    return { ...base, base_url: provider.baseUrl };
  }
  return base;
}
```

Anthropic 特殊处理：字段名为 `api_key`（与 langchain_anthropic 对应）。
Google 特殊处理：字段名为 `gemini_api_key`。

**写入时机：** 每次 `start()` / `restart()` 前重新生成，保证配置与用户设置同步。

### 3.2 环境变量注入（复用现有逻辑）

```typescript
const providerSecrets = Object.fromEntries(
  await Promise.all(
    settings.providers.map(async (provider) => [
      provider.apiKeyEnv,
      (await getSecret(provider.apiKeyEnv)) ?? undefined,
    ])
  )
);
// 注入到子进程 env，现有逻辑不变
```

### 3.3 config.yaml 读写方案

采用**方案 A（推荐）**：

在 `paths.ts` 中新增 `desktopModelsConfigPath`，指向 `runtimeDir/desktop-models.yaml`。

启动时生成该文件，通过后端支持的 config merge 机制（或直接覆写 `config.yaml` 的 `models` 字段）传给后端。

若后端不支持 config merge，则直接读取 `config.yaml`，替换 `models:` 段后写回。

---

## 四、涉及改动的文件清单

### Desktop 端
- `desktop/main/config.ts` — 扩展 `DesktopProviderSetting` 类型，清空默认 providers，新增 `PROVIDER_PRESETS` 常量表
- `desktop/main/processes.ts` — 启动前生成 models 配置写入文件
- `desktop/main/paths.ts` — 新增 `desktopModelsConfigPath`
- `desktop/preload/index.ts` — 无变化（Bridge 接口不变）
- `desktop/main/ipc.ts` — 无变化

### 前端
- `frontend/src/components/workspace/settings/model-settings-page.tsx` — 重构：空列表状态、Add Provider Dialog、厂商预设逻辑
- `frontend/src/core/i18n/locales/zh-CN.ts` — 新增 providerType 相关翻译 key
- `frontend/src/core/i18n/locales/en-US.ts` — 同上
- `frontend/src/core/i18n/locales/types.ts` — 新增类型字段

### 后端
- 无需改动（现有 `config.yaml` 热重载机制已满足需求）
