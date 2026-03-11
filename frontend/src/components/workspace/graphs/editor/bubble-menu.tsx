"use client";

import type { Editor } from "@tiptap/react";
import { BubbleMenu } from "@tiptap/react/menus";
import {
  BoldIcon,
  CodeIcon,
  HighlighterIcon,
  ItalicIcon,
  LinkIcon,
  StrikethroughIcon,
  UnderlineIcon,
} from "lucide-react";
import { useCallback, useRef, useState } from "react";

import { cn } from "@/lib/utils";

interface BubbleToolbarProps {
  editor: Editor;
}

function ToolbarButton({
  active,
  onClick,
  children,
  title,
}: {
  active?: boolean;
  onClick: () => void;
  children: React.ReactNode;
  title: string;
}) {
  return (
    <button
      onMouseDown={(e) => {
        e.preventDefault();
        onClick();
      }}
      title={title}
      className={cn(
        "flex size-8 items-center justify-center rounded-lg transition-colors",
        active
          ? "bg-accent text-foreground"
          : "text-muted-foreground hover:bg-accent/50 hover:text-foreground",
      )}
    >
      {children}
    </button>
  );
}

function HeadingButton({
  editor,
  level,
}: {
  editor: Editor;
  level: 1 | 2 | 3;
}) {
  const active = editor.isActive("heading", { level });
  return (
    <button
      onMouseDown={(e) => {
        e.preventDefault();
        editor.chain().focus().toggleHeading({ level }).run();
      }}
      title={`Heading ${level}`}
      className={cn(
        "flex size-8 items-center justify-center rounded-lg text-xs font-bold transition-colors",
        active
          ? "bg-accent text-foreground"
          : "text-muted-foreground hover:bg-accent/50 hover:text-foreground",
      )}
    >
      H{level}
    </button>
  );
}

export function DashboardBubbleMenu({ editor }: BubbleToolbarProps) {
  const [linkMode, setLinkMode] = useState(false);
  const [linkUrl, setLinkUrl] = useState("");
  const linkInputRef = useRef<HTMLInputElement>(null);

  const applyLink = useCallback(() => {
    if (linkUrl.trim()) {
      const url = linkUrl.startsWith("http") ? linkUrl : `https://${linkUrl}`;
      editor.chain().focus().setLink({ href: url }).run();
    } else {
      editor.chain().focus().unsetLink().run();
    }
    setLinkMode(false);
    setLinkUrl("");
  }, [editor, linkUrl]);

  const openLinkMode = useCallback(() => {
    const existing = editor.getAttributes("link").href as string | undefined;
    setLinkUrl(existing ?? "");
    setLinkMode(true);
    setTimeout(() => linkInputRef.current?.focus(), 50);
  }, [editor]);

  return (
    <BubbleMenu
      editor={editor}
      options={{ placement: "top" }}
    >
      <div className="flex items-center gap-0.5 rounded-xl border bg-popover p-1 shadow-lg">
        {linkMode ? (
          <div className="flex items-center gap-1 px-1">
            <LinkIcon className="size-3.5 shrink-0 text-muted-foreground" />
            <input
              ref={linkInputRef}
              type="url"
              placeholder="Paste link..."
              className="w-48 bg-transparent text-xs outline-none placeholder:text-muted-foreground/50"
              value={linkUrl}
              onChange={(e) => setLinkUrl(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  applyLink();
                }
                if (e.key === "Escape") {
                  setLinkMode(false);
                  setLinkUrl("");
                }
              }}
            />
            <button
              onMouseDown={(e) => {
                e.preventDefault();
                applyLink();
              }}
              className="rounded-md bg-foreground px-2 py-0.5 text-[10px] font-medium text-background"
            >
              Apply
            </button>
          </div>
        ) : (
          <>
            {/* Block type: Headings */}
            <HeadingButton editor={editor} level={1} />
            <HeadingButton editor={editor} level={2} />
            <HeadingButton editor={editor} level={3} />

            <div className="mx-0.5 h-5 w-px bg-border" />

            {/* Inline formatting */}
            <ToolbarButton
              active={editor.isActive("bold")}
              onClick={() => editor.chain().focus().toggleBold().run()}
              title="Bold"
            >
              <BoldIcon className="size-3.5" />
            </ToolbarButton>
            <ToolbarButton
              active={editor.isActive("italic")}
              onClick={() => editor.chain().focus().toggleItalic().run()}
              title="Italic"
            >
              <ItalicIcon className="size-3.5" />
            </ToolbarButton>
            <ToolbarButton
              active={editor.isActive("underline")}
              onClick={() => editor.chain().focus().toggleUnderline().run()}
              title="Underline"
            >
              <UnderlineIcon className="size-3.5" />
            </ToolbarButton>
            <ToolbarButton
              active={editor.isActive("strike")}
              onClick={() => editor.chain().focus().toggleStrike().run()}
              title="Strikethrough"
            >
              <StrikethroughIcon className="size-3.5" />
            </ToolbarButton>
            <ToolbarButton
              active={editor.isActive("code")}
              onClick={() => editor.chain().focus().toggleCode().run()}
              title="Inline Code"
            >
              <CodeIcon className="size-3.5" />
            </ToolbarButton>

            <div className="mx-0.5 h-5 w-px bg-border" />

            {/* Link */}
            <ToolbarButton
              active={editor.isActive("link")}
              onClick={openLinkMode}
              title="Link"
            >
              <LinkIcon className="size-3.5" />
            </ToolbarButton>

            {/* Highlight */}
            <ToolbarButton
              active={editor.isActive("highlight")}
              onClick={() => editor.chain().focus().toggleHighlight().run()}
              title="Highlight"
            >
              <HighlighterIcon className="size-3.5" />
            </ToolbarButton>
          </>
        )}
      </div>
    </BubbleMenu>
  );
}
