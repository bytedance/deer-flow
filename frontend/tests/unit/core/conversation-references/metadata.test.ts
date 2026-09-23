import { expect, test } from "@rstest/core";

import {
  CONVERSATION_REFERENCES_KWARG,
  buildConversationReferenceMetadata,
  readConversationReferences,
  type ConversationReference,
} from "@/core/conversation-references";

const references: ConversationReference[] = [
  { threadId: "thread-a", title: "Requirements review" },
  { threadId: "thread-b", title: "Design notes" },
];

test("metadata carries thread id and title only, under one display-only key", () => {
  expect(buildConversationReferenceMetadata(references)).toEqual({
    [CONVERSATION_REFERENCES_KWARG]: [
      { thread_id: "thread-a", title: "Requirements review" },
      { thread_id: "thread-b", title: "Design notes" },
    ],
  });
});

test("reading round-trips what build wrote", () => {
  expect(
    readConversationReferences(buildConversationReferenceMetadata(references)),
  ).toEqual(references);
});

test("metadata round-trips the source's custom agent when present", () => {
  const withAgent: ConversationReference[] = [
    { threadId: "thread-w", title: "Writer notes", agentName: "writer" },
  ];
  expect(buildConversationReferenceMetadata(withAgent)).toEqual({
    [CONVERSATION_REFERENCES_KWARG]: [
      { thread_id: "thread-w", title: "Writer notes", agent_name: "writer" },
    ],
  });
  expect(
    readConversationReferences(buildConversationReferenceMetadata(withAgent)),
  ).toEqual(withAgent);
});

test("reading tolerates missing, malformed and duplicate entries", () => {
  expect(readConversationReferences(undefined)).toEqual([]);
  expect(readConversationReferences({})).toEqual([]);
  expect(readConversationReferences({ conversation_references: "x" })).toEqual(
    [],
  );
  expect(
    readConversationReferences({
      conversation_references: [
        { thread_id: "thread-a", title: "Kept" },
        { thread_id: "thread-a", title: "Duplicate of the first" },
        { thread_id: 7, title: "Bad id" },
        { thread_id: "", title: "Empty id" },
        { thread_id: "thread-c" },
        { thread_id: "thread-d", title: "" },
        { thread_id: "thread-f", agent_name: 42 },
        { thread_id: "thread-g", agent_name: "" },
        null,
        "thread-e",
      ],
    }),
  ).toEqual([
    { threadId: "thread-a", title: "Kept" },
    { threadId: "thread-c", title: "" },
    { threadId: "thread-d", title: "" },
    { threadId: "thread-f", title: "" },
    { threadId: "thread-g", title: "" },
  ]);
});
