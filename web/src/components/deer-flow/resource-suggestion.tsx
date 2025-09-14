// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import type { MentionOptions } from "@tiptap/extension-mention";
import { ReactRenderer } from "@tiptap/react";
import {
  ResourceMentions,
  type ResourceMentionsProps,
} from "./resource-mentions";
import type { Instance, Props } from "tippy.js";
import tippy from "tippy.js";
import { resolveServiceURL } from "~/core/api/resolve-service-url";
import type { Resource } from "~/core/messages";

export const resourceSuggestion: MentionOptions["suggestion"] = {
  items: ({ query }) => {
    return fetch(resolveServiceURL(`rag/resources?query=${query}`), {
      method: "GET",
    })
      .then((res) => res.json())
      .then((res) => {
        return res.resources as Array<Resource>;
      })
      .catch((err) => {
        return [];
      });
  },

  render: () => {
    let reactRenderer: ReactRenderer<
      { onKeyDown: (args: { event: KeyboardEvent }) => boolean },
      ResourceMentionsProps
    >;
    let popup: Instance<Props>[] | null = null;

    return {
      onStart: (props) => {
        reactRenderer = new ReactRenderer(ResourceMentions, {
          props,
          editor: props.editor,
        });

        const clientRect = props.clientRect || (() => {
          const selection = props.editor.state.selection;
          const coords = props.editor.view.coordsAtPos(selection.from);
          return {
            top: coords.top,
            left: coords.left,
            right: coords.right,
            bottom: coords.bottom,
            width: 0,
            height: 0,
          };
        });

        popup = tippy("body", {
          getReferenceClientRect: clientRect as any,
          appendTo: () => document.body,
          content: reactRenderer.element,
          showOnCreate: true,
          interactive: true,
          trigger: "manual",
          placement: "top-start",
        });
      },

      onUpdate(props) {
        if (reactRenderer) {
          reactRenderer.updateProps(props);
        }

        if (popup?.[0] && !popup[0].state.isDestroyed) {
          const clientRect = props.clientRect || (() => {
            const selection = props.editor.state.selection;
            const coords = props.editor.view.coordsAtPos(selection.from);
            return {
              top: coords.top,
              left: coords.left,
              right: coords.right,
              bottom: coords.bottom,
              width: 0,
              height: 0,
            };
          });
          
          popup[0].setProps({
            getReferenceClientRect: clientRect as any,
          });
        }
      },

      onKeyDown(props) {
        if (props.event.key === "Escape") {
          popup?.[0]?.hide();

          return true;
        }

        return reactRenderer.ref?.onKeyDown(props) ?? false;
      },

      onExit() {
        popup?.[0]?.destroy();
        reactRenderer.destroy();
      },
    };
  },
};
