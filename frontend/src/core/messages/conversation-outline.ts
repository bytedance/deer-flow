import {
  extractTextFromMessage,
  stripUploadedFilesTag,
  type MessageGroup,
} from "./utils";

export const CONVERSATION_OUTLINE_MIN_TURNS = 5;
export const CONVERSATION_CHAPTER_TITLE_MAX_LENGTH = 48;

export type ConversationChapter = {
  id: string;
  groupIndex: number;
  title: string;
};

function normalizeChapterTitle(content: string, fallbackTitle: string): string {
  const normalized = stripUploadedFilesTag(content).replace(/\s+/g, " ").trim();
  if (!normalized) {
    return fallbackTitle;
  }

  const characters = Array.from(normalized);
  if (characters.length <= CONVERSATION_CHAPTER_TITLE_MAX_LENGTH) {
    return normalized;
  }
  return `${characters
    .slice(0, CONVERSATION_CHAPTER_TITLE_MAX_LENGTH)
    .join("")}…`;
}

export function buildConversationChapters(
  groups: readonly MessageGroup[],
  fallbackTitle: string,
): ConversationChapter[] {
  const chapters: ConversationChapter[] = [];

  groups.forEach((group, groupIndex) => {
    if (group.type !== "human") {
      return;
    }

    const message = group.messages[0];
    chapters.push({
      id: group.id ?? message?.id ?? `human-turn:${groupIndex}`,
      groupIndex,
      title: normalizeChapterTitle(
        message ? extractTextFromMessage(message) : "",
        fallbackTitle,
      ),
    });
  });

  return chapters;
}
