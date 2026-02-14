# 代码更改总结（按文件 diff，细到每一行）

基于 `git diff HEAD` 的完整 diff，按文件列出所有变更。删除/新增文件单独说明。

---

## 一、后端

### 1. `backend/CLAUDE.md`

```diff
@@ -156,7 +156,7 @@ FastAPI application on port 8001 with health check at `GET /health`.
 | **Skills** (`/api/skills`) | `GET /` - list skills; `GET /{name}` - details; `PUT /{name}` - update enabled; `POST /install` - install from .skill archive |
 | **Memory** (`/api/memory`) | `GET /` - memory data; `POST /reload` - force reload; `GET /config` - config; `GET /status` - config + data |
 | **Uploads** (`/api/threads/{id}/uploads`) | `POST /` - upload files (auto-converts PDF/PPT/Excel/Word); `GET /list` - list; `DELETE /{filename}` - delete |
-| **Artifacts** (`/api/threads/{id}/artifacts`) | `GET /{path}` - serve artifacts; `?download=true` for download with citation removal |
+| **Artifacts** (`/api/threads/{id}/artifacts`) | `GET /{path}` - serve artifacts; `?download=true` for file download |

 Proxied through nginx: `/api/langgraph/*` → LangGraph, all other `/api/*` → Gateway.
```

- **第 159 行**：表格中 Artifacts 描述由「download with citation removal」改为「file download」。

---

### 2. `backend/src/agents/lead_agent/prompt.py`

```diff
@@ -240,34 +240,8 @@ You have access to skills that provide optimized workflows for specific tasks. E
 - Action-Oriented: Focus on delivering results, not explaining processes
 </response_style>
 
-<citations_format>
-After web_search, ALWAYS include citations in your output:
-
-1. Start with a `<citations>` block in JSONL format listing all sources
-2. In content, use FULL markdown link format: [Short Title](full_url)
-
-**CRITICAL - Citation Link Format:**
-- CORRECT: `[TechCrunch](https://techcrunch.com/ai-trends)` - full markdown link with URL
-- WRONG: `[arXiv:2502.19166]` - missing URL, will NOT render as link
-- WRONG: `[Source]` - missing URL, will NOT render as link
-
-**Rules:**
-- Every citation MUST be a complete markdown link with URL: `[Title](https://...)`
-- Write content naturally, add citation link at end of sentence/paragraph
-- NEVER use bare brackets like `[arXiv:xxx]` or `[Source]` without URL
-
-**Example:**
-<citations>
-{{"id": "cite-1", "title": "AI Trends 2026", "url": "https://techcrunch.com/ai-trends", "snippet": "Tech industry predictions"}}
-{{"id": "cite-2", "title": "OpenAI Research", "url": "https://openai.com/research", "snippet": "Latest AI research developments"}}
-</citations>
-The key AI trends for 2026 include enhanced reasoning capabilities and multimodal integration [TechCrunch](https://techcrunch.com/ai-trends). Recent breakthroughs in language models have also accelerated progress [OpenAI](https://openai.com/research).
-</citations_format>
-
-
 <critical_reminders>
 - **Clarification First**: ALWAYS clarify unclear/missing/ambiguous requirements BEFORE starting work - never assume or guess
-- **Web search citations**: When you use web_search (or synthesize subagent results that used it), you MUST output the `<citations>` block and [Title](url) links as specified in citations_format so citations display for the user.
 {subagent_reminder}- Skill First: Always load the relevant skill before starting **complex** tasks.
```

```diff
@@ -341,7 +315,6 @@ def apply_prompt_template(subagent_enabled: bool = False) -> str:
     # Add subagent reminder to critical_reminders if enabled
     subagent_reminder = (
         "- **Orchestrator Mode**: You are a task orchestrator - decompose complex tasks into parallel sub-tasks and launch multiple subagents simultaneously. Synthesize results, don't execute directly.\n"
-        "- **Citations when synthesizing**: When you synthesize subagent results that used web search or cite sources, you MUST include a consolidated `<citations>` block (JSONL format) and use [Title](url) markdown links in your response so citations display correctly.\n"
         if subagent_enabled
         else ""
     )
```

- **删除**：`<citations_format>...</citations_format>` 整段（原约 243–266 行）、critical_reminders 中「Web search citations」一条、`apply_prompt_template` 中「Citations when synthesizing」一行。

---

### 3. `backend/src/gateway/routers/artifacts.py`

```diff
@@ -1,12 +1,10 @@
-import json
 import mimetypes
-import re
 import zipfile
 from pathlib import Path
 from urllib.parse import quote
 
-from fastapi import APIRouter, HTTPException, Request, Response
-from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
+from fastapi import APIRouter, HTTPException, Request
+from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, Response
 
 from src.gateway.path_utils import resolve_thread_virtual_path
```

- **第 1 行**：删除 `import json`。
- **第 3 行**：删除 `import re`。
- **第 6–7 行**：`fastapi` 中去掉 `Response`；`fastapi.responses` 中增加 `Response`（保留二进制 inline 返回用）。

```diff
@@ -24,40 +22,6 @@ def is_text_file_by_content(path: Path, sample_size: int = 8192) -> bool:
         return False
 
 
-def _extract_citation_urls(content: str) -> set[str]:
-    """Extract URLs from <citations> JSONL blocks. Format must match frontend core/citations/utils.ts."""
-    urls: set[str] = set()
-    for match in re.finditer(r"<citations>([\s\S]*?)</citations>", content):
-        for line in match.group(1).split("\n"):
-            line = line.strip()
-            if line.startswith("{"):
-                try:
-                    obj = json.loads(line)
-                    if "url" in obj:
-                        urls.add(obj["url"])
-                except (json.JSONDecodeError, ValueError):
-                    pass
-    return urls
-
-
-def remove_citations_block(content: str) -> str:
-    """Remove ALL citations from markdown (blocks, [cite-N], and citation links). Used for downloads."""
-    if not content:
-        return content
-
-    citation_urls = _extract_citation_urls(content)
-
-    result = re.sub(r"<citations>[\s\S]*?</citations>", "", content)
-    if "<citations>" in result:
-        result = re.sub(r"<citations>[\s\S]*$", "", result)
-    result = re.sub(r"\[cite-\d+\]", "", result)
-
-    for url in citation_urls:
-        result = re.sub(rf"\[[^\]]+\]\({re.escape(url)}\)", "", result)
-
-    return re.sub(r"\n{3,}", "\n\n", result).strip()
-
-
 def _extract_file_from_skill_archive(zip_path: Path, internal_path: str) -> bytes | None:
```

- **删除**：`_extract_citation_urls`、`remove_citations_block` 两个函数（约 25–62 行）。

```diff
@@ -172,24 +136,9 @@ async def get_artifact(thread_id: str, path: str, request: Request) -> FileRespo
 
     # Encode filename for Content-Disposition header (RFC 5987)
     encoded_filename = quote(actual_path.name)
-    
-    # Check if this is a markdown file that might contain citations
-    is_markdown = mime_type == "text/markdown" or actual_path.suffix.lower() in [".md", ".markdown"]
-    
+
     # if `download` query parameter is true, return the file as a download
     if request.query_params.get("download"):
-        # For markdown files, remove citations block before download
-        if is_markdown:
-            content = actual_path.read_text()
-            clean_content = remove_citations_block(content)
-            return Response(
-                content=clean_content.encode("utf-8"),
-                media_type="text/markdown",
-                headers={
-                    "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}",
-                    "Content-Type": "text/markdown; charset=utf-8"
-                }
-            )
         return FileResponse(path=actual_path, filename=actual_path.name, media_type=mime_type, headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}"})
 
     if mime_type and mime_type == "text/html":
```

- **删除**：`is_markdown` 判断及「markdown 时读文件 + remove_citations_block + Response」分支；download 时统一走 `FileResponse`。

---

### 4. `backend/src/subagents/builtins/general_purpose.py`

```diff
@@ -24,21 +24,10 @@ Do NOT use for simple, single-step operations.""",
 - Do NOT ask for clarification - work with the information provided
 </guidelines>
 
-<citations_format>
-If you used web_search (or similar) and cite sources, ALWAYS include citations in your output:
-1. Start with a `<citations>` block in JSONL format listing all sources (one JSON object per line)
-2. In content, use FULL markdown link format: [Short Title](full_url)
-- Every citation MUST be a complete markdown link with URL: [Title](https://...)
-- Example block:
-<citations>
-{"id": "cite-1", "title": "...", "url": "https://...", "snippet": "..."}
-</citations>
-</citations_format>
-
 <output_format>
 When you complete the task, provide:
 1. A brief summary of what was accomplished
-2. Key findings or results (with citation links when from web search)
+2. Key findings or results
 3. Any relevant file paths, data, or artifacts created
 4. Issues encountered (if any)
 </output_format>
```

- **删除**：`<citations_format>...</citations_format>` 整段。
- **第 40 行**：第 2 条由「Key findings or results (with citation links when from web search)」改为「Key findings or results」。

---

## 二、前端文档与工具

### 5. `frontend/AGENTS.md`

```diff
@@ -49,7 +49,6 @@ src/
 ├── core/                   # Core business logic
 │   ├── api/                # API client & data fetching
 │   ├── artifacts/          # Artifact management
-│   ├── citations/          # Citation handling
 │   ├── config/              # App configuration
 │   ├── i18n/               # Internationalization
```

- **第 52 行**：删除目录树中的 `citations/` 一行。

---

### 6. `frontend/CLAUDE.md`

```diff
@@ -30,7 +30,7 @@ Frontend (Next.js) ──▶ LangGraph SDK ──▶ LangGraph Backend (lead_age
                                               └── Tools & Skills
 ```
 
-The frontend is a stateful chat application. Users create **threads** (conversations), send messages, and receive streamed AI responses. The backend orchestrates agents that can produce **artifacts** (files/code), **todos**, and **citations**.
+The frontend is a stateful chat application. Users create **threads** (conversations), send messages, and receive streamed AI responses. The backend orchestrates agents that can produce **artifacts** (files/code) and **todos**.
 
 ### Source Layout (`src/`)
```

- **第 33 行**：「and **citations**」删除。

---

### 7. `frontend/README.md`

```diff
@@ -89,7 +89,6 @@ src/
 ├── core/                   # Core business logic
 │   ├── api/                # API client & data fetching
 │   ├── artifacts/          # Artifact management
-│   ├── citations/          # Citation handling
 │   ├── config/              # App configuration
 │   ├── i18n/               # Internationalization
```

- **第 92 行**：删除目录树中的 `citations/` 一行。

---

### 8. `frontend/src/lib/utils.ts`

```diff
@@ -8,5 +8,5 @@ export function cn(...inputs: ClassValue[]) {
 /** Shared class for external links (underline by default). */
 export const externalLinkClass =
   "text-primary underline underline-offset-2 hover:no-underline";
-/** For streaming / loading state when link may be a citation (no underline). */
+/** Link style without underline by default (e.g. for streaming/loading). */
 export const externalLinkClassNoUnderline = "text-primary hover:underline";
```

- **第 11 行**：仅注释修改，导出值未变。

---

## 三、前端组件

### 9. `frontend/src/components/workspace/artifacts/artifact-file-detail.tsx`

```diff
@@ -8,7 +8,6 @@ import {
   SquareArrowOutUpRightIcon,
   XIcon,
 } from "lucide-react";
-import * as React from "react";
 import { useCallback, useEffect, useMemo, useState } from "react";
 ...
@@ -21,7 +20,6 @@ import (
   ArtifactHeader,
   ArtifactTitle,
 } from "@/components/ai-elements/artifact";
-import { createCitationMarkdownComponents } from "@/components/ai-elements/inline-citation";
 import { Select, SelectItem } from "@/components/ui/select";
 ...
@@ -33,12 +31,6 @@ import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
 import { CodeEditor } from "@/components/workspace/code-editor";
 import { useArtifactContent } from "@/core/artifacts/hooks";
 import { urlOfArtifact } from "@/core/artifacts/utils";
-import type { Citation } from "@/core/citations";
-import {
-  contentWithoutCitationsFromParsed,
-  removeAllCitations,
-  useParsedCitations,
-} from "@/core/citations";
 import { useI18n } from "@/core/i18n/hooks";
 ...
@@ -48,9 +40,6 @@ import { cn } from "@/lib/utils";
 
 import { Tooltip } from "../tooltip";
 
-import { SafeCitationContent } from "../messages/safe-citation-content";
-import { useThread } from "../messages/context";
-
 import { useArtifacts } from "./context";
```

```diff
@@ -92,22 +81,13 @@ export function ArtifactFileDetail({
   const previewable = useMemo(() => {
     return (language === "html" && !isWriteFile) || language === "markdown";
   }, [isWriteFile, language]);
-  const { thread } = useThread();
   const { content } = useArtifactContent({
     threadId,
     filepath: filepathFromProps,
     enabled: isCodeFile && !isWriteFile,
   });
 
-  const parsed = useParsedCitations(
-    language === "markdown" ? (content ?? "") : "",
-  );
-  const cleanContent =
-    language === "markdown" && content ? parsed.cleanContent : (content ?? "");
-  const contentWithoutCitations =
-    language === "markdown" && content
-      ? contentWithoutCitationsFromParsed(parsed)
-      : (content ?? "");
+  const displayContent = content ?? "";
 
   const [viewMode, setViewMode] = useState<"code" | "preview">("code");
```

```diff
@@ -219,7 +199,7 @@ export function ArtifactFileDetail({
                 disabled={!content}
                 onClick={async () => {
                   try {
-                    await navigator.clipboard.writeText(contentWithoutCitations ?? "");
+                    await navigator.clipboard.writeText(displayContent ?? "");
                     toast.success(t.clipboard.copiedToClipboard);
 ...
@@ -255,27 +235,17 @@ export function ArtifactFileDetail({
           viewMode === "preview" &&
           language === "markdown" &&
           content && (
-            <SafeCitationContent
-              content={content}
-              isLoading={thread.isLoading}
-              rehypePlugins={streamdownPlugins.rehypePlugins}
-              className="flex size-full items-center justify-center p-4 my-0"
-              renderBody={(p) => (
-                <ArtifactFilePreview
-                  filepath={filepath}
-                  threadId={threadId}
-                  content={content}
-                  language={language ?? "text"}
-                  cleanContent={p.cleanContent}
-                  citationMap={p.citationMap}
-                />
-              )}
+            <ArtifactFilePreview
+              filepath={filepath}
+              threadId={threadId}
+              content={displayContent}
+              language={language ?? "text"}
             />
           )}
         {isCodeFile && viewMode === "code" && (
           <CodeEditor
             className="size-full resize-none rounded-none border-none"
-            value={cleanContent ?? ""}
+            value={displayContent ?? ""}
             readonly
           />
         )}
```

```diff
@@ -295,29 +265,17 @@ export function ArtifactFilePreview({
   threadId,
   content,
   language,
-  cleanContent,
-  citationMap,
 }: {
   filepath: string;
   threadId: string;
   content: string;
   language: string;
-  cleanContent: string;
-  citationMap: Map<string, Citation>;
 }) {
   if (language === "markdown") {
-    const components = createCitationMarkdownComponents({
-      citationMap,
-      syntheticExternal: true,
-    });
     return (
       <div className="size-full px-4">
-        <Streamdown
-          className="size-full"
-          {...streamdownPlugins}
-          components={components}
-        >
-          {cleanContent ?? ""}
+        <Streamdown className="size-full" {...streamdownPlugins}>
+          {content ?? ""}
         </Streamdown>
       </div>
     );
```

- 删除：React 命名空间、inline-citation、core/citations、SafeCitationContent、useThread；parsed/cleanContent/contentWithoutCitations 及引用解析逻辑。
- 新增：`displayContent = content ?? ""`；预览与复制、CodeEditor 均使用 `displayContent`；`ArtifactFilePreview` 仅保留 `content`/`language` 等，去掉 `cleanContent`/`citationMap` 与 `createCitationMarkdownComponents`。

---

### 10. `frontend/src/components/workspace/messages/message-group.tsx`

```diff
@@ -39,9 +39,7 @@ import { useArtifacts } from "../artifacts";
 import { FlipDisplay } from "../flip-display";
 import { Tooltip } from "../tooltip";
 
-import { useThread } from "./context";
-
-import { SafeCitationContent } from "./safe-citation-content";
+import { MarkdownContent } from "./markdown-content";
 
 export function MessageGroup({
```

```diff
@@ -120,7 +118,7 @@ export function MessageGroup({
                 <ChainOfThoughtStep
                   key={step.id}
                   label={
-                    <SafeCitationContent
+                    <MarkdownContent
                       content={step.reasoning ?? ""}
                       isLoading={isLoading}
                       rehypePlugins={rehypePlugins}
@@ -128,12 +126,7 @@ export function MessageGroup({
                   }
                 ></ChainOfThoughtStep>
               ) : (
-                <ToolCall
-                  key={step.id}
-                  {...step}
-                  isLoading={isLoading}
-                  rehypePlugins={rehypePlugins}
-                />
+                <ToolCall key={step.id} {...step} isLoading={isLoading} />
               ),
             )}
           {lastToolCallStep && (
@@ -143,7 +136,6 @@ export function MessageGroup({
                 {...lastToolCallStep}
                 isLast={true}
                 isLoading={isLoading}
-                rehypePlugins={rehypePlugins}
               />
             </FlipDisplay>
           )}
@@ -178,7 +170,7 @@ export function MessageGroup({
               <ChainOfThoughtStep
                 key={lastReasoningStep.id}
                 label={
-                  <SafeCitationContent
+                  <MarkdownContent
                     content={lastReasoningStep.reasoning ?? ""}
                     isLoading={isLoading}
                     rehypePlugins={rehypePlugins}
@@ -201,7 +193,6 @@ function ToolCall({
   result,
   isLast = false,
   isLoading = false,
-  rehypePlugins,
 }: {
   id?: string;
   messageId?: string;
@@ -210,15 +201,10 @@ function ToolCall({
   result?: string | Record<string, unknown>;
   isLast?: boolean;
   isLoading?: boolean;
-  rehypePlugins: ReturnType<typeof useRehypeSplitWordsIntoSpans>;
 }) {
   const { t } = useI18n();
   const { setOpen, autoOpen, autoSelect, selectedArtifact, select } =
     useArtifacts();
-  const { thread } = useThread();
-  const threadIsLoading = thread.isLoading;
-
-  const fileContent = typeof args.content === "string" ? args.content : "";
 
   if (name === "web_search") {
```

```diff
@@ -364,42 +350,27 @@ function ToolCall({
       }, 100);
     }
 
-    const isMarkdown =
-      path?.toLowerCase().endsWith(".md") ||
-      path?.toLowerCase().endsWith(".markdown");
-
     return (
-      <>
-        <ChainOfThoughtStep
-          key={id}
-          className="cursor-pointer"
-          label={description}
-          icon={NotebookPenIcon}
-          onClick={() => {
-            select(
-              new URL(
-                `write-file:${path}?message_id=${messageId}&tool_call_id=${id}`,
-              ).toString(),
-            );
-            setOpen(true);
-          }}
-        >
-          {path && (
-            <ChainOfThoughtSearchResult className="cursor-pointer">
-              {path}
-            </ChainOfThoughtSearchResult>
-          )}
-        </ChainOfThoughtStep>
-        {isMarkdown && (
-          <SafeCitationContent
-            content={fileContent}
-            isLoading={threadIsLoading && isLast}
-            rehypePlugins={rehypePlugins}
-            loadingOnly
-            className="mt-2 ml-8"
-          />
+      <ChainOfThoughtStep
+        key={id}
+        className="cursor-pointer"
+        label={description}
+        icon={NotebookPenIcon}
+        onClick={() => {
+          select(
+            new URL(
+              `write-file:${path}?message_id=${messageId}&tool_call_id=${id}`,
+            ).toString(),
+          );
+          setOpen(true);
+        }}
+      >
+        {path && (
+          <ChainOfThoughtSearchResult className="cursor-pointer">
+            {path}
+          </ChainOfThoughtSearchResult>
         )}
-      </>
+      </ChainOfThoughtStep>
     );
   } else if (name === "bash") {
```

- 两处 `SafeCitationContent` → `MarkdownContent`；ToolCall 去掉 `rehypePlugins` 及内部 `useThread`/`fileContent`；write_file 分支去掉 markdown 预览块（`isMarkdown` + `SafeCitationContent`），仅保留 `ChainOfThoughtStep` + path。

---

### 11. `frontend/src/components/workspace/messages/message-list-item.tsx`

```diff
@@ -12,7 +12,6 @@ import {
 } from "@/components/ai-elements/message";
 import { Badge } from "@/components/ui/badge";
 import { resolveArtifactURL } from "@/core/artifacts/utils";
-import { removeAllCitations } from "@/core/citations";
 import {
   extractContentFromMessage,
   extractReasoningContentFromMessage,
@@ -24,7 +23,7 @@ import { humanMessagePlugins } from "@/core/streamdown";
 import { cn } from "@/lib/utils";
 
 import { CopyButton } from "../copy-button";
-import { SafeCitationContent } from "./safe-citation-content";
+import { MarkdownContent } from "./markdown-content";
 ...
@@ -54,11 +53,11 @@ export function MessageListItem({
       >
         <div className="flex gap-1">
           <CopyButton
-            clipboardData={removeAllCitations(
+            clipboardData={
               extractContentFromMessage(message) ??
               extractReasoningContentFromMessage(message) ??
               ""
-            )}
+            }
           />
         </div>
       </MessageToolbar>
@@ -154,7 +153,7 @@ function MessageContent_({
   return (
     <AIElementMessageContent className={className}>
       {filesList}
-      <SafeCitationContent
+      <MarkdownContent
         content={contentToParse}
         isLoading={isLoading}
         rehypePlugins={[...rehypePlugins, [rehypeKatex, { output: "html" }]]}
```

- 删除 `removeAllCitations` 与 `SafeCitationContent` 引用；复制改为原始内容；渲染改为 `MarkdownContent`。

---

### 12. `frontend/src/components/workspace/messages/message-list.tsx`

```diff
@@ -26,7 +26,7 @@ import { StreamingIndicator } from "../streaming-indicator";
 
 import { MessageGroup } from "./message-group";
 import { MessageListItem } from "./message-list-item";
-import { SafeCitationContent } from "./safe-citation-content";
+import { MarkdownContent } from "./markdown-content";
 import { MessageListSkeleton } from "./skeleton";
 ...
@@ -69,7 +69,7 @@ export function MessageList({
             const message = group.messages[0];
             if (message && hasContent(message)) {
               return (
-                <SafeCitationContent
+                <MarkdownContent
                   key={group.id}
                   content={extractContentFromMessage(message)}
                   isLoading={thread.isLoading}
@@ -89,7 +89,7 @@ export function MessageList({
             return (
               <div className="w-full" key={group.id}>
                 {group.messages[0] && hasContent(group.messages[0]) && (
-                  <SafeCitationContent
+                  <MarkdownContent
                     content={extractContentFromMessage(group.messages[0])}
                     isLoading={thread.isLoading}
                     rehypePlugins={rehypePlugins}
```

- 三处：import 与两处渲染均由 `SafeCitationContent` 改为 `MarkdownContent`，props 不变。

---

### 13. `frontend/src/components/workspace/messages/subtask-card.tsx`

```diff
@@ -29,7 +29,7 @@ import { cn } from "@/lib/utils";
 
 import { FlipDisplay } from "../flip-display";
 
-import { SafeCitationContent } from "./safe-citation-content";
+import { MarkdownContent } from "./markdown-content";
 ...
@@ -153,7 +153,7 @@ export function SubtaskCard({
               <ChainOfThoughtStep
                 label={
                   task.result ? (
-                    <SafeCitationContent
+                    <MarkdownContent
                       content={task.result}
                       isLoading={false}
                       rehypePlugins={rehypePlugins}
```

- import 与一处渲染：`SafeCitationContent` → `MarkdownContent`。

---

### 14. 新增 `frontend/src/components/workspace/messages/markdown-content.tsx`

（当前工作区新增，未在 git 中）

```ts
"use client";

import type { ImgHTMLAttributes } from "react";
import type { ReactNode } from "react";

import {
  MessageResponse,
  type MessageResponseProps,
} from "@/components/ai-elements/message";
import { streamdownPlugins } from "@/core/streamdown";

export type MarkdownContentProps = {
  content: string;
  isLoading: boolean;
  rehypePlugins: MessageResponseProps["rehypePlugins"];
  className?: string;
  remarkPlugins?: MessageResponseProps["remarkPlugins"];
  isHuman?: boolean;
  img?: (props: ImgHTMLAttributes<HTMLImageElement> & { threadId?: string; maxWidth?: string }) => ReactNode;
};

/** Renders markdown content. */
export function MarkdownContent({
  content,
  rehypePlugins,
  className,
  remarkPlugins = streamdownPlugins.remarkPlugins,
  img,
}: MarkdownContentProps) {
  if (!content) return null;
  const components = img ? { img } : undefined;
  return (
    <MessageResponse
      className={className}
      remarkPlugins={remarkPlugins}
      rehypePlugins={rehypePlugins}
      components={components}
    >
      {content}
    </MessageResponse>
  );
}
```

- 纯 Markdown 渲染组件，无引用解析或 loading 占位逻辑。

---

### 15. 删除 `frontend/src/components/workspace/messages/safe-citation-content.tsx`

- 原约 85 行；提供引用解析、loading、renderBody/loadingOnly、cleanContent/citationMap。已由 `MarkdownContent` 替代，整文件删除。

---

### 16. 删除 `frontend/src/components/ai-elements/inline-citation.tsx`

- 原约 289 行；提供 `createCitationMarkdownComponents` 等，用于将 `[cite-N]`/URL 渲染为可点击引用。仅被 artifact 预览使用，已移除后整文件删除。

---

## 四、前端 core

### 17. 删除 `frontend/src/core/citations/index.ts`

- 原 13 行，导出：`contentWithoutCitationsFromParsed`、`extractDomainFromUrl`、`isExternalUrl`、`parseCitations`、`removeAllCitations`、`shouldShowCitationLoading`、`syntheticCitationFromLink`、`useParsedCitations`、类型 `Citation`/`ParseCitationsResult`/`UseParsedCitationsResult`。整文件删除。

---

### 18. 删除 `frontend/src/core/citations/use-parsed-citations.ts`

- 原 28 行，`useParsedCitations(content)` 与 `UseParsedCitationsResult`。整文件删除。

---

### 19. 删除 `frontend/src/core/citations/utils.ts`

- 原 226 行，解析 `<citations>`/`[cite-N]`、buildCitationMap、removeAllCitations、contentWithoutCitationsFromParsed 等。整文件删除。

---

### 20. `frontend/src/core/i18n/locales/types.ts`

```diff
@@ -115,12 +115,6 @@ export interface Translations {
     startConversation: string;
   };
 
-  // Citations
-  citations: {
-    loadingCitations: string;
-    loadingCitationsWithCount: (count: number) => string;
-  };
-
   // Chats
   chats: {
```

- 删除 `Translations.citations` 及其两个字段。

---

### 21. `frontend/src/core/i18n/locales/zh-CN.ts`

```diff
@@ -164,12 +164,6 @@ export const zhCN: Translations = {
     startConversation: "开始新的对话以查看消息",
   },
 
-  // Citations
-  citations: {
-    loadingCitations: "正在整理引用...",
-    loadingCitationsWithCount: (count: number) => `正在整理 ${count} 个引用...`,
-  },
-
   // Chats
   chats: {
```

- 删除 `citations` 命名空间。

---

### 22. `frontend/src/core/i18n/locales/en-US.ts`

```diff
@@ -167,13 +167,6 @@ export const enUS: Translations = {
     startConversation: "Start a conversation to see messages here",
   },
 
-  // Citations
-  citations: {
-    loadingCitations: "Organizing citations...",
-    loadingCitationsWithCount: (count: number) =>
-      `Organizing ${count} citation${count === 1 ? "" : "s"}...`,
-  },
-
   // Chats
   chats: {
```

- 删除 `citations` 命名空间。

---

## 五、技能与 Demo

### 23. `skills/public/github-deep-research/SKILL.md`

```diff
@@ -147,5 +147,5 @@ Save report as: `research_{topic}_{YYYYMMDD}.md`
 3. **Triangulate claims** - 2+ independent sources
 4. **Note conflicting info** - Don't hide contradictions
 5. **Distinguish fact vs opinion** - Label speculation clearly
-6. **Cite inline** - Reference sources near claims
+6. **Reference sources** - Add source references near claims where applicable
 7. **Update as you go** - Don't wait until end to synthesize
```

- 第 150 行：一条措辞修改。

---

### 24. `skills/public/market-analysis/SKILL.md`

```diff
@@ -15,7 +15,7 @@ This skill generates professional, consulting-grade market analysis reports in M
 - Follow the **"Visual Anchor → Data Contrast → Integrated Analysis"** flow per sub-chapter
 - Produce insights following the **"Data → User Psychology → Strategy Implication"** chain
 - Embed pre-generated charts and construct comparison tables
-- Generate inline citations formatted per **GB/T 7714-2015** standards
+- Include references formatted per **GB/T 7714-2015** where applicable
 - Output reports entirely in Chinese with professional consulting tone
 ...
@@ -36,7 +36,7 @@ The skill expects the following inputs from the upstream agentic workflow:
 | **Analysis Framework Outline** | Defines the logic flow and general topics for the report | Yes |
 | **Data Summary** | The source of truth containing raw numbers and metrics | Yes |
 | **Chart Files** | Local file paths for pre-generated chart images | Yes |
-| **External Search Findings** | URLs and summaries for inline citations | Optional |
+| **External Search Findings** | URLs and summaries for inline references | Optional |
 ...
@@ -87,7 +87,7 @@ The report **MUST NOT** stop after the Conclusion — it **MUST** include Refere
 - **Tone**: McKinsey/BCG — Authoritative, Objective, Professional
 - **Language**: All headings and content strictly in **Chinese**
 - **Number Formatting**: Use English commas for thousands separators (`1,000` not `1，000`)
-- **Data Citation**: **Bold** important viewpoints and key numbers
+- **Data emphasis**: **Bold** important viewpoints and key numbers
 ...
@@ -109,11 +109,9 @@ Every insight must connect **Data → User Psychology → Strategy Implication**
    treating male audiences only as a secondary gift-giving segment."
 ```
 
-### Citations & References
-- **Inline**: Use `[\[Index\]](URL)` format (e.g., `[\[1\]](https://example.com)`)
-- **Placement**: Append citations at the end of sentences using information from External Search Findings
-- **Index Assignment**: Sequential starting from **1** based on order of appearance
-- **References Section**: Formatted strictly per **GB/T 7714-2015**
+### References
+- **Inline**: Use markdown links for sources (e.g. `[Source Title](URL)`) when using External Search Findings
+- **References section**: Formatted strictly per **GB/T 7714-2015**
 ...
@@ -183,7 +181,7 @@ Before considering the report complete, verify:
 - [ ] All headings are in Chinese with proper numbering (no "Chapter/Part/Section")
 - [ ] Charts are embedded with `![Description](path)` syntax
 - [ ] Numbers use English commas for thousands separators
-- [ ] Inline citations use `[\[N\]](URL)` format
+- [ ] Inline references use markdown links where applicable
 - [ ] References section follows GB/T 7714-2015
```

- 多处：核心能力、输入表、Data Citation、Citations & References 小节与检查项，改为「references / 引用」表述并去掉 `[\[N\]](URL)` 格式要求。

---

### 25. `frontend/public/demo/threads/.../user-data/outputs/research_deerflow_20260201.md`

```diff
@@ -1,12 +1,3 @@
-<citations>
-{"id": "cite-1", "title": "DeerFlow GitHub Repository", "url": "https://github.com/bytedance/deer-flow", "snippet": "..."}
-...（共 7 条 JSONL）
-</citations>
 # DeerFlow Deep Research Report
 
 - **Research Date:** 2026-02-01
```

- 删除文件开头的 `<citations>...</citations>` 整块（9 行），正文从 `# DeerFlow Deep Research Report` 开始。

---

### 26. `frontend/public/demo/threads/.../thread.json`

- **主要变更**：某条 `write_file` 的 `args.content` 中，将原来的「`<citations>...\n</citations>\n# DeerFlow Deep Research Report\n\n...`」改为「`# DeerFlow Deep Research Report\n\n...`」，即去掉 `<citations>...</citations>` 块，保留其后全文。
- **其他**：一处 `present_files` 的 `filepaths` 由单行数组改为多行格式；文件末尾增加/统一换行。
- 消息顺序、结构及其他字段未改。

---

## 六、统计

| 项目 | 数量 |
|------|------|
| 修改文件 | 18 |
| 新增文件 | 1（markdown-content.tsx） |
| 删除文件 | 5（safe-citation-content.tsx, inline-citation.tsx, core/citations/* 共 3 个） |
| 总行数变化 | +62 / -894（diff stat） |

以上为按文件、细到每一行 diff 的代码更改总结。
