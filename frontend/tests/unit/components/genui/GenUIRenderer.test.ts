/* @vitest-environment jsdom */

import React from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { GenUIRenderer } from "@/components/genui/GenUIRenderer";
import { type UIBlock, useBlockStore } from "@/core/genui/store";

vi.mock("@/core/genui/registry", () => ({
  getBlockComponent: () =>
    function MockBlock({
      block,
    }: {
      block: { interactionState?: { status?: string } };
    }) {
      return React.createElement(
        "div",
        null,
        block.interactionState?.status ?? "visible",
      );
    },
}));

vi.mock("@/core/genui/sanitizer", () => ({
  sanitizeProps: (_component: string, props: Record<string, unknown>) => props,
}));

vi.mock("@/core/genui/validator", () => ({
  validateProps: () => ({ success: true }),
}));

function makeFormBlock(
  block_id: string,
  callback_id = "daily-report-equipment",
): UIBlock {
  return {
    schema_version: "1.0",
    type: "ui_block",
    action: "create",
    block_id,
    component: "form",
    interactive: true,
    callback_id,
    props: {},
  };
}

describe("GenUIRenderer", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    globalThis.IS_REACT_ACT_ENVIRONMENT = true;
    useBlockStore.getState().reset();
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    React.act(() => {
      root.unmount();
    });
    container.remove();
    useBlockStore.getState().reset();
  });

  it("looks up submitted interaction state by block instance", () => {
    const block = makeFormBlock("equipment-form-old");
    useBlockStore.setState({
      blocks: new Map([[block.block_id, block]]),
      interactions: new Map([[block.block_id, { status: "submitted" }]]),
    });

    React.act(() => {
      root.render(
        React.createElement(GenUIRenderer, {
          block,
          threadId: "thread-1",
        }),
      );
    });

    expect(container.textContent).toContain("submitted");
  });
});
