/**
 * Text that must never appear in a default view of scheduled tasks or the
 * chat goal bar: UUIDs, task/run ids, ISO timestamps, five-field cron
 * strings, internal enum or field names and goal stand-down codes
 * (`contracts/thread_goal_contract.json`). Pure (no test-runner imports) so
 * the Playwright helper (`readable.ts`) and the unit helper
 * (`tests/unit/helpers/readable.ts`) share one list.
 */
export const RAW_IDENTIFIER_PATTERNS: readonly RegExp[] = [
  /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i,
  /\btask-(run-)?[0-9a-f]{16,}\b/,
  /\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/,
  /(^|\s)[\d*/,-]+(\s[\d*/,-]+){4}(\s|$)/,
  /\b(fresh_thread_per_run|reuse_thread|lead_agent|goal_objective|max_runs|end_at|unmet|stop_scheduled_task|schedule_task)\b/,
  /\b(blocked:[a-z_]+|max_continuations_reached|no_progress_detected|token_capped|evaluator_failed|no_durable_end_of_turn|thread_changed_(after_evaluation|before_continuation)|goal_outcome|stand_down_reason|last_evaluation)\b/,
];

/** The patterns `text` matches, with the matched text, for a readable failure message. */
export function findRawIdentifiers(text: string): string[] {
  return RAW_IDENTIFIER_PATTERNS.flatMap((pattern) => {
    const match = pattern.exec(text);
    return match ? [`${pattern.source} → "${match[0].trim()}"`] : [];
  });
}
