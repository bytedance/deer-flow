"use client";

import { capabilityCopy } from "@/core/capabilities/copy";
import { useCapabilityInstallations } from "@/core/capabilities/hooks";
import { useI18n } from "@/core/i18n/hooks";

function Selection({
  adapter,
  value,
  onChange,
}: {
  adapter: "mcp" | "skills";
  value: string[] | null;
  onChange: (value: string[] | null) => void;
}) {
  const { locale, t } = useI18n();
  const copy = capabilityCopy(locale);
  const query = useCapabilityInstallations(adapter);
  const items = (query.data?.items ?? []).filter(
    (item) => item.installed && item.selectable !== false,
  );
  const options = new Map(
    items.map((item) => [
      adapter === "skills" ? item.reference : item.id,
      item.name,
    ]),
  );
  for (const id of value ?? [])
    if (!options.has(id)) options.set(id, `${id} (${copy.unavailable})`);
  return (
    <fieldset className="space-y-2 rounded-lg border p-3">
      <legend className="px-1 text-sm font-medium">
        {adapter === "mcp" ? copy.plugins : copy.skills}
      </legend>
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={value === null}
          onChange={(event) => onChange(event.target.checked ? null : [])}
        />
        {copy.all}
      </label>
      {query.isLoading && (
        <p className="text-muted-foreground text-xs">{t.common.loading}</p>
      )}
      {query.isError && (
        <p role="alert" className="text-destructive text-xs">
          {copy.adapterError}
        </p>
      )}
      {value !== null && (
        <div className="max-h-44 space-y-2 overflow-y-auto">
          {[...options].map(([id, name]) => (
            <label key={id} className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={value.includes(id)}
                onChange={(event) =>
                  onChange(
                    event.target.checked
                      ? [...value, id]
                      : value.filter((item) => item !== id),
                  )
                }
              />
              {name}
            </label>
          ))}
        </div>
      )}
    </fieldset>
  );
}
export function AgentCapabilitySelection({
  plugins,
  skills,
  onPluginsChange,
  onSkillsChange,
}: {
  plugins: string[] | null;
  skills: string[] | null;
  onPluginsChange: (value: string[] | null) => void;
  onSkillsChange: (value: string[] | null) => void;
}) {
  const { locale } = useI18n();
  const copy = capabilityCopy(locale);
  return (
    <details className="space-y-3 rounded-lg border p-3">
      <summary className="cursor-pointer text-sm font-medium">
        {copy.selectionTitle}
      </summary>
      <p className="text-muted-foreground text-xs leading-5">{copy.hint}</p>
      <Selection adapter="mcp" value={plugins} onChange={onPluginsChange} />
      <Selection adapter="skills" value={skills} onChange={onSkillsChange} />
    </details>
  );
}
