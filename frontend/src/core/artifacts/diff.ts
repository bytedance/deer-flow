export type ThreadFileDiffLineKind =
  | "context"
  | "added"
  | "removed"
  | "modified";

interface DiffOperationContext {
  kind: "context";
  content: string;
}

interface DiffOperationAdded {
  kind: "added";
  content: string;
}

interface DiffOperationRemoved {
  kind: "removed";
  content: string;
}

type DiffOperation =
  | DiffOperationContext
  | DiffOperationAdded
  | DiffOperationRemoved;

export interface ThreadFileDiffLine {
  kind: ThreadFileDiffLineKind;
  beforeLineNumber: number | null;
  afterLineNumber: number | null;
  beforeContent: string;
  afterContent: string;
}

export interface ThreadFileDiff {
  lines: ThreadFileDiffLine[];
  summary: {
    added: number;
    removed: number;
    modified: number;
  };
}

function splitIntoLines(content: string) {
  return content.split("\n");
}

function buildOperations(beforeLines: string[], afterLines: string[]) {
  const beforeLength = beforeLines.length;
  const afterLength = afterLines.length;
  const dp = Array.from({ length: beforeLength + 1 }, () =>
    Array<number>(afterLength + 1).fill(0),
  );

  for (let beforeIndex = beforeLength - 1; beforeIndex >= 0; beforeIndex -= 1) {
    for (
      let afterIndex = afterLength - 1;
      afterIndex >= 0;
      afterIndex -= 1
    ) {
      if (beforeLines[beforeIndex] === afterLines[afterIndex]) {
        dp[beforeIndex]![afterIndex] = dp[beforeIndex + 1]![afterIndex + 1]! + 1;
      } else {
        dp[beforeIndex]![afterIndex] = Math.max(
          dp[beforeIndex + 1]![afterIndex]!,
          dp[beforeIndex]![afterIndex + 1]!,
        );
      }
    }
  }

  const operations: DiffOperation[] = [];
  let beforeIndex = 0;
  let afterIndex = 0;

  while (beforeIndex < beforeLength && afterIndex < afterLength) {
    if (beforeLines[beforeIndex] === afterLines[afterIndex]) {
      operations.push({
        kind: "context",
        content: beforeLines[beforeIndex]!,
      });
      beforeIndex += 1;
      afterIndex += 1;
      continue;
    }

    if (dp[beforeIndex + 1]![afterIndex]! >= dp[beforeIndex]![afterIndex + 1]!) {
      operations.push({
        kind: "removed",
        content: beforeLines[beforeIndex]!,
      });
      beforeIndex += 1;
    } else {
      operations.push({
        kind: "added",
        content: afterLines[afterIndex]!,
      });
      afterIndex += 1;
    }
  }

  while (beforeIndex < beforeLength) {
    operations.push({
      kind: "removed",
      content: beforeLines[beforeIndex]!,
    });
    beforeIndex += 1;
  }

  while (afterIndex < afterLength) {
    operations.push({
      kind: "added",
      content: afterLines[afterIndex]!,
    });
    afterIndex += 1;
  }

  return operations;
}

function flushChanges({
  addedLines,
  afterLineNumber,
  beforeLineNumber,
  diffLines,
  removedLines,
  summary,
}: {
  addedLines: string[];
  afterLineNumber: number;
  beforeLineNumber: number;
  diffLines: ThreadFileDiffLine[];
  removedLines: string[];
  summary: ThreadFileDiff["summary"];
}) {
  const pairedLength = Math.min(removedLines.length, addedLines.length);
  let nextBeforeLineNumber = beforeLineNumber;
  let nextAfterLineNumber = afterLineNumber;

  for (let index = 0; index < pairedLength; index += 1) {
    diffLines.push({
      kind: "modified",
      beforeLineNumber: nextBeforeLineNumber,
      afterLineNumber: nextAfterLineNumber,
      beforeContent: removedLines[index]!,
      afterContent: addedLines[index]!,
    });
    nextBeforeLineNumber += 1;
    nextAfterLineNumber += 1;
    summary.modified += 1;
  }

  for (const removedLine of removedLines.slice(pairedLength)) {
    diffLines.push({
      kind: "removed",
      beforeLineNumber: nextBeforeLineNumber,
      afterLineNumber: null,
      beforeContent: removedLine,
      afterContent: "",
    });
    nextBeforeLineNumber += 1;
    summary.removed += 1;
  }

  for (const addedLine of addedLines.slice(pairedLength)) {
    diffLines.push({
      kind: "added",
      beforeLineNumber: null,
      afterLineNumber: nextAfterLineNumber,
      beforeContent: "",
      afterContent: addedLine,
    });
    nextAfterLineNumber += 1;
    summary.added += 1;
  }

  return {
    beforeLineNumber: nextBeforeLineNumber,
    afterLineNumber: nextAfterLineNumber,
  };
}

export function buildThreadFileDiff({
  beforeContent,
  afterContent,
}: {
  beforeContent: string;
  afterContent: string;
}): ThreadFileDiff {
  const operations = buildOperations(
    splitIntoLines(beforeContent),
    splitIntoLines(afterContent),
  );
  const lines: ThreadFileDiffLine[] = [];
  const summary = {
    added: 0,
    removed: 0,
    modified: 0,
  };

  let beforeLineNumber = 1;
  let afterLineNumber = 1;
  let removedLines: string[] = [];
  let addedLines: string[] = [];

  const flushPendingChanges = () => {
    if (removedLines.length === 0 && addedLines.length === 0) {
      return;
    }

    const next = flushChanges({
      addedLines,
      afterLineNumber,
      beforeLineNumber,
      diffLines: lines,
      removedLines,
      summary,
    });
    beforeLineNumber = next.beforeLineNumber;
    afterLineNumber = next.afterLineNumber;
    removedLines = [];
    addedLines = [];
  };

  for (const operation of operations) {
    if (operation.kind === "context") {
      flushPendingChanges();
      lines.push({
        kind: "context",
        beforeLineNumber,
        afterLineNumber,
        beforeContent: operation.content,
        afterContent: operation.content,
      });
      beforeLineNumber += 1;
      afterLineNumber += 1;
      continue;
    }

    if (operation.kind === "removed") {
      removedLines.push(operation.content);
      continue;
    }

    addedLines.push(operation.content);
  }

  flushPendingChanges();

  return {
    lines,
    summary,
  };
}
