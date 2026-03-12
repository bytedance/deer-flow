"use client";

import {
    Code2Icon,
    DownloadIcon,
    EyeIcon,
    FileTextIcon,
} from "lucide-react";
import { useMemo, useState } from "react";
import { Streamdown } from "streamdown";

import { Button } from "@/components/ui/button";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { CodeEditor } from "@/components/workspace/code-editor";
import { CitationLink } from "@/components/workspace/citations/citation-link";
import { streamdownPlugins } from "@/core/streamdown";
import { cn } from "@/lib/utils";

interface DocumentWorkspaceProps {
    className?: string;
    content?: string | null;
    format?: "html" | "markdown";
    title?: string;
    downloadUrl?: string;
}

export function DocumentWorkspace({
    className,
    content,
    format = "html",
    title,
    downloadUrl,
}: DocumentWorkspaceProps) {
    const [viewMode, setViewMode] = useState<"preview" | "code">("preview");

    const isEmpty = !content;

    if (isEmpty) {
        return (
            <div
                className={cn(
                    "flex size-full flex-col items-center justify-center gap-3 text-muted-foreground",
                    className,
                )}
            >
                <div className="flex size-16 items-center justify-center rounded-2xl bg-muted">
                    <FileTextIcon className="size-7" />
                </div>
                <p className="text-sm">Document will appear here</p>
                <p className="text-xs text-muted-foreground/60">Ask the AI to create a document</p>
            </div>
        );
    }

    return (
        <div className={cn("flex size-full flex-col bg-background", className)}>
            {/* Header */}
            <div className="flex h-12 shrink-0 items-center justify-between border-b px-4">
                <div className="flex items-center gap-2">
                    <FileTextIcon className="size-4 text-muted-foreground" />
                    <h2 className="text-sm font-medium truncate max-w-[300px]">
                        {title || "Document"}
                    </h2>
                    <span className="rounded-full bg-muted px-2 py-0.5 text-[10px] font-medium uppercase text-muted-foreground">
                        {format}
                    </span>
                </div>
                <div className="flex items-center gap-2">
                    <ToggleGroup
                        type="single"
                        variant="outline"
                        size="sm"
                        value={viewMode}
                        onValueChange={(value) => {
                            if (value) setViewMode(value as "preview" | "code");
                        }}
                    >
                        <ToggleGroupItem value="preview">
                            <EyeIcon className="size-3.5" />
                        </ToggleGroupItem>
                        <ToggleGroupItem value="code">
                            <Code2Icon className="size-3.5" />
                        </ToggleGroupItem>
                    </ToggleGroup>
                    {downloadUrl && (
                        <a href={downloadUrl} target="_blank" rel="noopener noreferrer">
                            <Button variant="ghost" size="icon" className="size-8">
                                <DownloadIcon className="size-4" />
                            </Button>
                        </a>
                    )}
                </div>
            </div>

            {/* Content */}
            <div className="min-h-0 flex-1 overflow-auto">
                {viewMode === "preview" && format === "html" && (
                    <iframe
                        className="size-full"
                        title="Document preview"
                        srcDoc={content}
                        sandbox="allow-same-origin"
                        style={{ border: "none" }}
                    />
                )}
                {viewMode === "preview" && format === "markdown" && (
                    <div className="mx-auto max-w-3xl px-6 py-8">
                        <Streamdown
                            className="size-full"
                            {...streamdownPlugins}
                            components={{ a: CitationLink }}
                        >
                            {content ?? ""}
                        </Streamdown>
                    </div>
                )}
                {viewMode === "code" && (
                    <CodeEditor
                        className="size-full resize-none rounded-none border-none"
                        value={content ?? ""}
                        readonly
                    />
                )}
            </div>
        </div>
    );
}
