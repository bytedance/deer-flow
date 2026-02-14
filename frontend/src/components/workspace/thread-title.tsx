import { FlipDisplay } from "./flip-display";

export function ThreadTitle({
  threadTitle,
}: {
  className?: string;
  threadId: string;
  threadTitle: string;
}) {
  return <FlipDisplay uniqueKey={threadTitle}>{threadTitle}</FlipDisplay>;
}
