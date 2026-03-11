"use client";

import Color from "@tiptap/extension-color";
import Highlight from "@tiptap/extension-highlight";
import Image from "@tiptap/extension-image";
import Link from "@tiptap/extension-link";
import Placeholder from "@tiptap/extension-placeholder";
import { TextStyle } from "@tiptap/extension-text-style";
import Underline from "@tiptap/extension-underline";
import {
  type JSONContent,
  type Editor,
  EditorContent,
  useEditor,
} from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import { useCallback, useEffect, useImperativeHandle, useRef, forwardRef } from "react";

import { uploadFiles } from "@/core/uploads/api";

import { DashboardBubbleMenu } from "./bubble-menu";
import { ChartNode } from "./chart-node";
import { MetricNode } from "./metric-node";
import { MetricRowNode } from "./metric-row-node";
import { NarrativeNode } from "./narrative-node";
import SlashCommandMenu from "./slash-command-menu";

/**
 * Upload an image file to the thread's /uploads endpoint and return the serving URL.
 * Falls back to base64 data URL if no threadId is available.
 */
async function uploadImageFile(file: File, threadId?: string): Promise<string> {
  if (threadId) {
    const response = await uploadFiles(threadId, [file]);
    if (response.success && response.files.length > 0) {
      return response.files[0]!.artifact_url;
    }
  }
  // Fallback: base64
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as string);
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

export interface DashboardEditorHandle {
  getEditor: () => Editor | null;
  /** Replace editor content programmatically (e.g. from AI agent). Resets the dirty flag. */
  setContent: (content: JSONContent) => void;
  /** Insert an image from a File (uploads to thread, then inserts). */
  insertImageFromFile: (file: File) => void;
}

interface DashboardEditorRawProps {
  content: JSONContent;
  readOnly?: boolean;
  threadId?: string;
  /** Called when the editor content changes (debounce externally). */
  onContentChange?: (content: JSONContent) => void;
}

const DashboardEditorRaw = forwardRef<
  DashboardEditorHandle,
  DashboardEditorRawProps
>(function DashboardEditorRaw({ content, readOnly = false, threadId, onContentChange }, ref) {
  // Store threadId in a ref so editorProps callbacks always see the latest value
  const threadIdRef = useRef(threadId);
  threadIdRef.current = threadId;

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
      Underline,
      TextStyle,
      Color,
      Highlight.configure({ multicolor: true }),
      Link.configure({
        openOnClick: false,
        HTMLAttributes: {
          class: "text-blue-600 underline cursor-pointer hover:text-blue-700",
        },
      }),
      Image.configure({
        inline: false,
        allowBase64: true,
        HTMLAttributes: {
          class: "dashboard-image",
        },
      }),
      ChartNode,
      MetricNode,
      MetricRowNode,
      NarrativeNode,
    ],
    immediatelyRender: false,
    editable: !readOnly,
    content,
    editorProps: {
      attributes: {
        class: "outline-none min-h-full",
      },
      handleDrop(view, event, _slice, moved) {
        if (moved || !event.dataTransfer?.files.length) return false;
        const file = event.dataTransfer.files[0];
        if (!file?.type.startsWith("image/")) return false;
        event.preventDefault();
        void uploadImageFile(file, threadIdRef.current).then((src) => {
          const pos = view.posAtCoords({ left: event.clientX, top: event.clientY });
          if (pos) {
            const node = view.state.schema.nodes.image!.create({ src });
            const tr = view.state.tr.insert(pos.pos, node);
            view.dispatch(tr);
          }
        });
        return true;
      },
      handlePaste(_view, event) {
        const items = event.clipboardData?.items;
        if (!items) return false;
        for (const item of items) {
          if (item.type.startsWith("image/")) {
            event.preventDefault();
            const file = item.getAsFile();
            if (!file) continue;
            const editorInstance = editor;
            if (!editorInstance) return false;
            void uploadImageFile(file, threadIdRef.current).then((src) => {
              editorInstance
                .chain()
                .focus()
                .insertContent({ type: "image", attrs: { src } })
                .run();
            });
            return true;
          }
        }
        return false;
      },
    },
  });

  // Track whether the user has made manual edits since last programmatic content set.
  // Once dirty, we never overwrite from the content prop — only via explicit setContent().
  const dirtyRef = useRef(false);
  const initialContentSetRef = useRef(false);

  const setContentProgrammatically = useCallback(
    (newContent: JSONContent) => {
      if (!editor) return;
      dirtyRef.current = false;
      queueMicrotask(() => {
        editor.commands.setContent(newContent);
        // Reset dirty after setContent since the transaction listener will fire
        dirtyRef.current = false;
      });
    },
    [editor],
  );

  useImperativeHandle(ref, () => ({
    getEditor: () => editor,
    setContent: setContentProgrammatically,
    insertImageFromFile: (file: File) => {
      if (!editor) return;
      void uploadImageFile(file, threadIdRef.current).then((src) => {
        editor
          .chain()
          .focus()
          .insertContent({ type: "image", attrs: { src } })
          .run();
      });
    },
  }));

  // Store callback in ref so the editor listener always sees the latest
  const onContentChangeRef = useRef(onContentChange);
  onContentChangeRef.current = onContentChange;

  // Mark editor as dirty when user makes manual edits + notify parent
  useEffect(() => {
    if (!editor) return;
    const handler = () => {
      // Only mark dirty after initial content has been set
      if (initialContentSetRef.current) {
        dirtyRef.current = true;
        onContentChangeRef.current?.(editor.getJSON());
      }
    };
    editor.on("update", handler);
    return () => {
      editor.off("update", handler);
    };
  }, [editor]);

  // Set content from prop — but only on initial load or when not dirty.
  // Page switches are handled by the key={activePage} prop which remounts the component.
  useEffect(() => {
    if (!editor) return;
    if (dirtyRef.current) return; // User has edited — don't overwrite

    queueMicrotask(() => {
      editor.commands.setContent(content);
      // Mark initial content as set so subsequent edits trigger dirty
      initialContentSetRef.current = true;
      dirtyRef.current = false;
    });
  }, [content, editor]);

  if (!editor) return null;

  return (
    <div className="dashboard-editor relative h-full pl-8">
      <EditorContent editor={editor} className="h-full" />
      {!readOnly && (
        <>
          <SlashCommandMenu editor={editor} threadId={threadId} />
          <DashboardBubbleMenu editor={editor} />
        </>
      )}
    </div>
  );
});

export default DashboardEditorRaw;
