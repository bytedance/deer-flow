import { Card, CardContent, CardHeader } from "@/components/ui/card";
import type { Translations } from "@/core/i18n/locales/types";
import { formatUsageDate, modelUsageRows } from "@/core/usage/format";
import type { UsageSummary } from "@/core/usage/types";

const cell = "px-4 py-3 text-right whitespace-nowrap tabular-nums";

export function UsageOverview({
  usage,
  locale,
  text,
}: {
  usage: UsageSummary;
  locale: string;
  text: Translations["usage"];
}) {
  const count = (value: number) => value.toLocaleString(locale);
  const models = modelUsageRows(usage.by_model);
  const peak = Math.max(1, ...usage.days.map((day) => day.total_tokens));
  const input = usage.days.reduce((sum, day) => sum + day.input_tokens, 0);
  const output = usage.days.reduce((sum, day) => sum + day.output_tokens, 0);
  const hasRuns = usage.total_runs > 0;
  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2">
        <Summary
          label={text.tokens}
          value={count(usage.total_tokens)}
          testId="usage-total-tokens"
        />
        <Summary
          label={text.runs}
          value={count(usage.total_runs)}
          testId="usage-total-runs"
        />
      </div>

      <Card>
        <CardHeader>
          <h2 className="font-semibold">{text.daily}</h2>
          <p className="text-muted-foreground text-sm">{text.timezoneNote}</p>
          <p className="text-muted-foreground text-sm tabular-nums">
            {text.inputTokens}: {count(input)} · {text.outputTokens}:{" "}
            {count(output)}
          </p>
        </CardHeader>
        <CardContent className="space-y-5">
          {!hasRuns ? (
            <p className="text-muted-foreground py-8 text-center text-sm">
              {text.noUsage}
            </p>
          ) : (
            <div
              aria-hidden="true"
              className="flex h-40 items-end gap-1 border-b px-1"
            >
              {usage.days.map((day) => (
                <div
                  key={day.date}
                  className="flex h-full min-w-0 flex-1 items-end"
                  title={`${formatUsageDate(day.date, locale)}: ${count(day.total_tokens)}`}
                >
                  <div
                    className="bg-primary/75 hover:bg-primary w-full rounded-t-sm transition-colors"
                    style={{
                      height: `${Math.max(day.total_tokens > 0 ? 2 : 0, (day.total_tokens / peak) * 100)}%`,
                    }}
                  />
                </div>
              ))}
            </div>
          )}
          {hasRuns && usage.days.length > 0 && (
            <div
              className="text-muted-foreground flex justify-between text-xs"
              aria-hidden="true"
            >
              <span>{formatUsageDate(usage.days[0]!.date, locale)}</span>
              <span>
                {formatUsageDate(
                  usage.days[usage.days.length - 1]!.date,
                  locale,
                )}
              </span>
            </div>
          )}
          {hasRuns && (
            <details>
              <summary className="cursor-pointer text-sm font-medium">
                {text.dailyDetails}
              </summary>
              <div className="mt-3 overflow-x-auto">
                <table className="w-full text-sm" aria-label={text.daily}>
                  <thead>
                    <tr className="text-muted-foreground border-b">
                      <th scope="col" className="px-4 py-3 text-left">
                        {text.date}
                      </th>
                      <th scope="col" className={cell}>
                        {text.inputTokens}
                      </th>
                      <th scope="col" className={cell}>
                        {text.outputTokens}
                      </th>
                      <th scope="col" className={cell}>
                        {text.runs}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {usage.days.map((day) => (
                      <tr key={day.date} className="border-b last:border-0">
                        <th
                          scope="row"
                          className="px-4 py-3 text-left font-normal whitespace-nowrap"
                        >
                          {formatUsageDate(day.date, locale)}
                        </th>
                        <td className={cell}>{count(day.input_tokens)}</td>
                        <td className={cell}>{count(day.output_tokens)}</td>
                        <td className={cell}>{count(day.runs)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <h2 className="font-semibold">{text.models}</h2>
        </CardHeader>
        <CardContent>
          {models.length === 0 ? (
            <p className="text-muted-foreground py-4 text-sm">
              {text.noModels}
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm" aria-label={text.models}>
                <thead>
                  <tr className="text-muted-foreground border-b">
                    <th scope="col" className="px-4 py-3 text-left">
                      {text.model}
                    </th>
                    <th scope="col" className={cell}>
                      {text.tokens}
                    </th>
                    <th scope="col" className={cell}>
                      {text.cachedTokens}
                    </th>
                    <th scope="col" className={cell}>
                      {text.runs}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {models.map((model) => (
                    <tr key={model.name} className="border-b last:border-0">
                      <th
                        scope="row"
                        className="max-w-60 px-4 py-3 text-left font-medium break-words"
                      >
                        {model.name}
                      </th>
                      <td className={cell}>{count(model.tokens)}</td>
                      <td className={cell}>{count(model.cache_read_tokens)}</td>
                      <td className={cell}>{count(model.runs)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function Summary({
  label,
  value,
  testId,
}: {
  label: string;
  value: string;
  testId: string;
}) {
  return (
    <Card className="gap-2">
      <CardHeader className="text-muted-foreground text-sm">{label}</CardHeader>
      <CardContent
        className="text-2xl font-semibold tabular-nums"
        data-testid={testId}
      >
        {value}
      </CardContent>
    </Card>
  );
}
