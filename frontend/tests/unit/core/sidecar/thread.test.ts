import { expect, test } from "@rstest/core";

import {
  SIDECAR_METADATA_KEY,
  buildSidecarThreadMetadata,
  isSidecarThread,
  shouldShowInPrimaryThreadLists,
} from "@/core/sidecar/thread";

test("builds sidecar thread metadata from parent thread and context", () => {
  const metadata = buildSidecarThreadMetadata("parent-1", {
    type: "referenced_message",
    label: "Assistant message",
    messageId: "msg-1",
    role: "assistant",
    content: "Answer",
  });

  expect(metadata).toEqual({
    [SIDECAR_METADATA_KEY]: true,
    parent_thread_id: "parent-1",
    sidecar_context_type: "referenced_message",
    sidecar_context_label: "Assistant message",
    sidecar_context_count: 1,
    referenced_message_id: "msg-1",
    referenced_message_ids: ["msg-1"],
    referenced_message_role: "assistant",
    referenced_message_roles: ["assistant"],
  });
});

test("builds searchable sidecar thread metadata from multiple contexts", () => {
  const metadata = buildSidecarThreadMetadata("parent-1", [
    {
      type: "referenced_message",
      label: "Assistant message #1",
      messageId: "msg-1",
      role: "assistant",
      content: "First answer",
    },
    {
      type: "referenced_message",
      label: "User message #2",
      messageId: "msg-2",
      role: "user",
      content: "Follow-up request",
    },
  ] as never);

  expect(metadata).toMatchObject({
    [SIDECAR_METADATA_KEY]: true,
    parent_thread_id: "parent-1",
    sidecar_context_type: "referenced_message",
    sidecar_context_label: "Assistant message #1",
    referenced_message_id: "msg-1",
    referenced_message_role: "assistant",
    sidecar_context_count: 2,
    referenced_message_ids: ["msg-1", "msg-2"],
    referenced_message_roles: ["assistant", "user"],
  });
});

test("keeps referenced ids/roles parallel when quoting one message twice", () => {
  const metadata = buildSidecarThreadMetadata("parent-1", [
    {
      type: "referenced_message",
      label: "Selected assistant text #1",
      messageId: "msg-1",
      role: "assistant",
      content: "First fragment",
    },
    {
      type: "referenced_message",
      label: "Selected assistant text #1",
      messageId: "msg-1",
      role: "assistant",
      content: "Second fragment",
    },
  ] as never);

  expect(metadata.sidecar_context_count).toBe(2);
  expect(metadata.referenced_message_ids).toEqual(["msg-1", "msg-1"]);
  expect(metadata.referenced_message_roles).toEqual(["assistant", "assistant"]);
  expect(metadata.referenced_message_ids).toHaveLength(
    metadata.referenced_message_roles.length,
  );
  expect(metadata.referenced_message_ids).toHaveLength(
    metadata.sidecar_context_count,
  );
});

test("identifies sidecar threads and hides them from primary thread lists", () => {
  const sidecar = {
    thread_id: "sidecar-1",
    metadata: { [SIDECAR_METADATA_KEY]: true },
  };
  const primary = {
    thread_id: "primary-1",
    metadata: {},
  };

  expect(isSidecarThread(sidecar)).toBe(true);
  expect(shouldShowInPrimaryThreadLists(sidecar)).toBe(false);
  expect(isSidecarThread(primary)).toBe(false);
  expect(shouldShowInPrimaryThreadLists(primary)).toBe(true);
});
