"use client";

import Placeholder from "@tiptap/extension-placeholder";
import { EditorContent, useEditor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import { useEffect } from "react";

import type { ArtifactGroup } from "../types";

import { artifactToTiptapContent } from "./artifact-to-tiptap";
import { ChartNode } from "./chart-node";
import { MetricNode } from "./metric-node";
import { MetricRowNode } from "./metric-row-node";
import SlashCommandMenu from "./slash-command-menu";

interface DashboardEditorProps {
  artifact: ArtifactGroup;
  readOnly?: boolean;
}

export default function DashboardEditor({ artifact, readOnly = false }: DashboardEditorProps) {
  const editor = useEditor({
    extensions: [
      StarterKit.configure({
        heading: {
          levels: [1, 2, 3],
        },
      }),
      Placeholder.configure({
        placeholder: 'Type "/" for commands...',
        showOnlyWhenEditable: true,
        showOnlyCurrent: true,
      }),
      ChartNode,
      MetricNode,
      MetricRowNode,
    ],
    immediatelyRender: false,
    editable: !readOnly,
    content: artifactToTiptapContent(artifact),
    editorProps: {
      attributes: {
        class: "outline-none min-h-full",
      },
    },
  });

  useEffect(() => {
    if (editor) {
      // Defer to avoid flushSync inside React render cycle
      queueMicrotask(() => {
        editor.commands.setContent(artifactToTiptapContent(artifact));
      });
    }
  }, [artifact, editor]);

  if (!editor) return null;

  return (
    <div className="dashboard-editor relative h-full pl-8">
      <EditorContent editor={editor} className="h-full" />
      {!readOnly && <SlashCommandMenu editor={editor} />}
    </div>
  );
}
