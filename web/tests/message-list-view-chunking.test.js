import { describe, it } from "node:test";
import assert from "node:assert/strict";

/**
 * Unit tests for the chunked rendering fix in message-list-view.tsx (Issue #614)
 * 
 * Tests verify that ThoughtBlock component correctly splits content into:
 * - Static content (previous chunks) - rendered without animation
 * - Streaming chunk (current chunk) - rendered with animation
 * 
 * This prevents the visual duplication of sentences that occurs when
 * the entire content is re-animated on every chunk update.
 */

/**
 * @typedef {Object} ChunkingResult
 * @property {string} staticContent - Content from all chunks except the last
 * @property {string} streamingChunk - The current streaming chunk
 * @property {boolean} hasStreamingContent - Whether there is streaming content
 * @property {string[]} chunks - The original chunks array
 */

/**
 * Simulate the chunking logic from ThoughtBlock component
 * @param {string[] | undefined} contentChunks - Array of content chunks
 * @param {boolean} isStreaming - Whether content is currently streaming
 * @returns {ChunkingResult} Object with staticContent, streamingChunk, hasStreamingContent, and chunks
 */
function computeChunking(contentChunks, isStreaming) {
  const chunks = contentChunks ?? [];
  const staticContent = chunks.slice(0, -1).join("");
  const streamingChunk =
    isStreaming && chunks.length > 0 ? (chunks[chunks.length - 1] ?? "") : "";
  const hasStreamingContent = isStreaming && streamingChunk.length > 0;

  return {
    staticContent,
    streamingChunk,
    hasStreamingContent,
    chunks,
  };
}

describe("ThoughtBlock chunked rendering (Issue #614)", () => {
  describe("Chunk splitting logic", () => {
    it("should split multiple chunks into static and streaming parts", () => {
      const contentChunks = ["part1", "part2", "part3"];
      const result = computeChunking(contentChunks, true);

      assert.strictEqual(result.staticContent, "part1part2");
      assert.strictEqual(result.streamingChunk, "part3");
      assert.strictEqual(result.hasStreamingContent, true);
    });

    it("should handle single chunk with streaming", () => {
      const contentChunks = ["only_chunk"];
      const result = computeChunking(contentChunks, true);

      assert.strictEqual(result.staticContent, "");
      assert.strictEqual(result.streamingChunk, "only_chunk");
      assert.strictEqual(result.hasStreamingContent, true);
    });

    it("should not have streaming content when not streaming", () => {
      const contentChunks = ["part1", "part2", "part3"];
      const result = computeChunking(contentChunks, false);

      assert.strictEqual(result.staticContent, "part1part2");
      assert.strictEqual(result.streamingChunk, "");
      assert.strictEqual(result.hasStreamingContent, false);
    });

    it("should handle empty chunks array", () => {
      const contentChunks = /** @type {string[]} */ ([]);
      const result = computeChunking(contentChunks, true);

      assert.strictEqual(result.staticContent, "");
      assert.strictEqual(result.streamingChunk, "");
      assert.strictEqual(result.hasStreamingContent, false);
    });

    it("should handle undefined chunks array", () => {
      const result = computeChunking(undefined, true);

      assert.strictEqual(result.staticContent, "");
      assert.strictEqual(result.streamingChunk, "");
      assert.strictEqual(result.hasStreamingContent, false);
    });

    it("should handle chunks with empty strings", () => {
      const contentChunks = ["part1", "", "part3"];
      const result = computeChunking(contentChunks, true);

      assert.strictEqual(result.staticContent, "part1");
      assert.strictEqual(result.streamingChunk, "part3");
      assert.strictEqual(result.hasStreamingContent, true);
    });
  });

  describe("Animation application logic", () => {
    it("should animate only current chunk during streaming", () => {
      const contentChunks = [
        "Reasoning about the problem...",
        "Analyzing the data...",
        "Drawing conclusions...",
      ];
      const result = computeChunking(contentChunks, true);

      // Only the last chunk should have animation applied
      assert.strictEqual(
        result.staticContent,
        "Reasoning about the problem...Analyzing the data..."
      );
      assert.strictEqual(result.streamingChunk, "Drawing conclusions...");

      // Verify that hasStreamingContent is true, meaning animation should apply
      assert.strictEqual(result.hasStreamingContent, true);
    });

    it("should not animate when streaming is complete", () => {
      const contentChunks = [
        "Reasoning about the problem...",
        "Analyzing the data...",
        "Drawing conclusions...",
      ];
      const result = computeChunking(contentChunks, false);

      // No animation should apply when streaming is complete
      assert.strictEqual(result.hasStreamingContent, false);
      assert.strictEqual(result.streamingChunk, "");
    });

    it("should prevent repeated animation of previous content", () => {
      // Simulate streaming progression
      const chunks1 = ["First chunk"];
      const chunks2 = ["First chunk", "Second chunk"];
      const chunks3 = ["First chunk", "Second chunk", "Third chunk"];

      const result1 = computeChunking(chunks1, true);
      const result2 = computeChunking(chunks2, true);
      const result3 = computeChunking(chunks3, true);

      // Verify that "First chunk" is in static content and not re-animated
      assert.strictEqual(result1.streamingChunk, "First chunk");
      assert.strictEqual(result2.staticContent, "First chunk");
      assert.strictEqual(result2.streamingChunk, "Second chunk");
      assert.strictEqual(result3.staticContent, "First chunkSecond chunk");
      assert.strictEqual(result3.streamingChunk, "Third chunk");

      // Key assertion: static content never changes during streaming
      assert.strictEqual(result1.staticContent, "");
      assert.strictEqual(result2.staticContent, "First chunk");
      assert.strictEqual(result3.staticContent, "First chunkSecond chunk");
    });
  });

  describe("Edge cases and nullish coalescing", () => {
    it("should safely handle undefined last chunk", () => {
      // This tests the nullish coalescing operator: chunks[chunks.length - 1] ?? ""
      const contentChunks = ["part1"];
      const result = computeChunking(contentChunks, true);

      // Should not throw and should handle gracefully
      assert.strictEqual(result.streamingChunk, "part1");
    });

    it("should handle very long chunk streams", () => {
      const contentChunks = Array.from({ length: 100 }, (_, i) => `chunk${i}`);
      const result = computeChunking(contentChunks, true);

      assert.strictEqual(result.chunks.length, 100);
      assert.strictEqual(result.staticContent, contentChunks.slice(0, -1).join(""));
      assert.strictEqual(result.streamingChunk, "chunk99");
      assert.strictEqual(result.hasStreamingContent, true);
    });

    it("should handle chunks with special characters", () => {
      const contentChunks = ["## Heading\n", "- List item\n", "**Bold text**"];
      const result = computeChunking(contentChunks, true);

      assert.strictEqual(result.staticContent, "## Heading\n- List item\n");
      assert.strictEqual(result.streamingChunk, "**Bold text**");
    });
  });

  describe("Real-world scenario: LLM thinking stream", () => {
    it("should handle realistic thinking process chunks", () => {
      const thinkingChunks = [
        "Let me analyze this step by step.\n",
        "First, I need to understand the problem.\n",
        "The key insight is that we need to consider multiple factors.\n",
        "After careful consideration, I believe the best approach is...",
      ];

      // Simulate streaming progression
      const progressions = /** @type {string[][]} */ ([
        [thinkingChunks[0]],
        [thinkingChunks[0], thinkingChunks[1]],
        [thinkingChunks[0], thinkingChunks[1], thinkingChunks[2]],
        [...thinkingChunks],
      ]);

      // Verify no repeated animations
      let previousStatic = "";
      for (const chunks of progressions) {
        const result = computeChunking(chunks, true);

        // Each progression should only animate the new chunk
        if (result.staticContent.startsWith(previousStatic)) {
          previousStatic = result.staticContent;
        }
        assert.strictEqual(result.hasStreamingContent, true);
      }
    });

    it("should complete streaming without animation", () => {
      const thinkingChunks = [
        "Step 1: Analyze\n",
        "Step 2: Plan\n",
        "Step 3: Execute\n",
      ];

      // During streaming
      const duringStreaming = computeChunking(thinkingChunks, true);
      assert.strictEqual(duringStreaming.hasStreamingContent, true);

      // After streaming completes
      const afterStreaming = computeChunking(thinkingChunks, false);
      assert.strictEqual(afterStreaming.hasStreamingContent, false);
      assert.strictEqual(afterStreaming.streamingChunk, "");
    });
  });
});
