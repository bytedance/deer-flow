import type { ScheduledTask } from "./types";

/** Literal, case-insensitive title/prompt matching; blank queries match all tasks. */
export function matchesScheduledTaskQuery(
  task: Pick<ScheduledTask, "title" | "prompt">,
  query: string,
): boolean {
  const needle = query.trim().toLowerCase();
  return (
    !needle ||
    task.title.toLowerCase().includes(needle) ||
    task.prompt.toLowerCase().includes(needle)
  );
}
