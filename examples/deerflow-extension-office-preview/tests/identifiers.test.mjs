import assert from "node:assert/strict";
import test from "node:test";

import { createUniqueIdAllocator } from "../ui/identifiers.js";

test("allocates distinct exact names without parsing user-supplied identifiers", () => {
  const allocate = createUniqueIdAllocator(
    ["office-0", "office-2", "office-1-0", "office-01", "unrelated"],
    "office-",
  );
  assert.equal(allocate(), "office-1");
  assert.equal(allocate(), "office-3");
  assert.equal(allocate(), "office-4");
});

test("consumes a large one-shot source once and skips all occupied identifiers", () => {
  const count = 100000;
  let reads = 0;
  function* names() {
    for (let index = 0; index < count; index++) {
      reads++;
      // Include the crafted-file shape from the review as well as exact collisions.
      yield `office-${index}-0`;
      yield `office-${index}`;
    }
  }
  const allocate = createUniqueIdAllocator(names(), "office-");
  assert.equal(allocate(), `office-${count}`);
  assert.equal(allocate(), `office-${count + 1}`);
  assert.equal(reads, count);
});

test("supports numeric OOXML ids and independent document lifetimes", () => {
  const first = createUniqueIdAllocator(["100000", "100002"], "", 100000);
  const second = createUniqueIdAllocator([], "", 100000);
  assert.equal(first(), "100001");
  assert.equal(first(), "100003");
  assert.equal(second(), "100000");
});
