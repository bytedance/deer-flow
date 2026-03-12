"use client";

import {
    ChevronRightIcon,
    FileTextIcon,
    MoreVerticalIcon,
    SendIcon,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { ScrollArea, ScrollBar } from "@/components/ui/scroll-area";
import {
    WorkspaceBody,
    WorkspaceContainer,
    WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import { useI18n } from "@/core/i18n/hooks";
import { useThreads } from "@/core/threads/hooks";
import { titleOfThread } from "@/core/threads/utils";
import { formatTimeAgo } from "@/core/utils/datetime";
import { cn } from "@/lib/utils";

interface Template {
    id: string;
    name: string;
    description: string;
    prompt: string;
    colors: string[];
    format: "html" | "markdown";
}

const TEMPLATES: Template[] = [
    {
        id: "business-report",
        name: "Business Report",
        description: "Professional quarterly report",
        prompt: "Create a professional quarterly business report with executive summary, financial highlights, operational review, and strategic outlook. Use a clean corporate layout with data tables.",
        colors: ["#2563eb", "#1e40af", "#3b82f6"],
        format: "html",
    },
    {
        id: "whitepaper",
        name: "Whitepaper",
        description: "Technical whitepaper",
        prompt: "Create a technical whitepaper about 'The Future of AI Agents in Enterprise'. Include abstract, introduction, current landscape, architecture overview, use cases, challenges, and conclusion. Use professional HTML formatting.",
        colors: ["#059669", "#10b981", "#34d399"],
        format: "html",
    },
    {
        id: "project-guide",
        name: "Project Guide",
        description: "Step-by-step guide document",
        prompt: "Create a comprehensive step-by-step guide for 'Setting Up a Modern CI/CD Pipeline'. Include introduction, prerequisites, setup steps, best practices, troubleshooting, and next steps. Use Markdown format.",
        colors: ["#7c3aed", "#8b5cf6", "#a78bfa"],
        format: "markdown",
    },
    {
        id: "meeting-memo",
        name: "Meeting Memo",
        description: "Structured meeting notes",
        prompt: "Create a structured meeting memo template with attendees, agenda items, discussion summary, action items with owners and deadlines, and next meeting date. Use HTML format with a professional layout.",
        colors: ["#f59e0b", "#d97706", "#fbbf24"],
        format: "html",
    },
    {
        id: "research-article",
        name: "Research Article",
        description: "Academic-style article",
        prompt: "Create a research article about 'Impact of Large Language Models on Software Development Productivity'. Include abstract, methodology, findings with statistics, discussion, and references. Use Markdown format.",
        colors: ["#ef4444", "#dc2626", "#f87171"],
        format: "markdown",
    },
    {
        id: "proposal",
        name: "Project Proposal",
        description: "Client-facing project proposal",
        prompt: "Create a project proposal for building a 'Customer Intelligence Dashboard'. Include executive summary, problem statement, proposed solution, timeline, budget estimate, and team. Use professional HTML formatting.",
        colors: ["#06b6d4", "#0891b2", "#22d3ee"],
        format: "html",
    },
];

function TemplateCard({ template, onClick }: { template: Template; onClick: () => void }) {
    return (
        <button
            className="group flex w-48 shrink-0 flex-col overflow-hidden rounded-xl border bg-card transition-shadow hover:shadow-lg"
            onClick={onClick}
        >
            <div
                className="flex h-28 items-center justify-center p-3"
                style={{
                    background: `linear-gradient(135deg, ${template.colors[0]}20, ${template.colors[1]}30, ${template.colors[2]}15)`,
                }}
            >
                <FileTextIcon className="size-10" style={{ color: template.colors[0], opacity: 0.5 }} />
            </div>
            <div className="p-3">
                <div className="flex items-center gap-1.5">
                    <p className="text-left text-xs font-medium">{template.name}</p>
                    <span className="rounded bg-muted px-1 py-0.5 text-[8px] font-medium uppercase text-muted-foreground">
                        {template.format === "html" ? "HTML" : "MD"}
                    </span>
                </div>
                <p className="text-left text-[10px] text-muted-foreground mt-0.5">{template.description}</p>
            </div>
        </button>
    );
}

export default function DocumentsHomePage() {
    const { t } = useI18n();
    const router = useRouter();
    const { data: threads } = useThreads();
    const [prompt, setPrompt] = useState("");

    useEffect(() => {
        document.title = `Documents - ${t.pages.appName}`;
    }, [t.pages.appName]);

    const handleSubmit = useCallback(
        (text?: string) => {
            const msg = text ?? prompt;
            if (!msg.trim()) return;
            sessionStorage.setItem("documents-initial-prompt", msg);
            router.push("/workspace/documents/new");
        },
        [prompt, router],
    );

    const handleTemplateClick = useCallback(
        (template: Template) => {
            handleSubmit(template.prompt);
        },
        [handleSubmit],
    );

    return (
        <WorkspaceContainer>
            <WorkspaceHeader />
            <WorkspaceBody>
                <div className="flex size-full flex-col overflow-auto">
                    {/* Hero + Prompt */}
                    <div className="mx-auto flex w-full max-w-3xl flex-col items-center px-6 pt-12 pb-8">
                        <div className="flex items-center gap-2 text-2xl font-semibold">
                            <FileTextIcon className="size-6" />
                            <span>What document would you like to create?</span>
                        </div>

                        <div className="mt-6 w-full">
                            <div className="flex items-center gap-2 rounded-xl border bg-card px-4 py-3 shadow-sm focus-within:ring-2 focus-within:ring-primary/20">
                                <input
                                    className="min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
                                    placeholder="Describe your document..."
                                    value={prompt}
                                    onChange={(e) => setPrompt(e.target.value)}
                                    onKeyDown={(e) => {
                                        if (e.key === "Enter" && !e.shiftKey) {
                                            e.preventDefault();
                                            handleSubmit();
                                        }
                                    }}
                                />
                                <Button
                                    size="icon-sm"
                                    className="shrink-0 rounded-full"
                                    disabled={!prompt.trim()}
                                    onClick={() => handleSubmit()}
                                >
                                    <SendIcon className="size-3.5" />
                                </Button>
                            </div>
                        </div>
                    </div>

                    {/* Recent Documents */}
                    {threads && threads.length > 0 && (
                        <section className="px-6 pb-6">
                            <div className="mx-auto max-w-6xl">
                                <div className="flex items-center justify-between pb-3">
                                    <h2 className="text-lg font-semibold">Recent Documents</h2>
                                    <Link
                                        href="/workspace/chats"
                                        className="text-muted-foreground hover:text-foreground flex items-center gap-0.5 text-xs"
                                    >
                                        View All
                                        <ChevronRightIcon className="size-3" />
                                    </Link>
                                </div>
                                <ScrollArea className="w-full">
                                    <div className="flex gap-4 pb-4">
                                        {threads.slice(0, 8).map((thread) => (
                                            <Link
                                                key={thread.thread_id}
                                                href={`/workspace/documents/${thread.thread_id}`}
                                                className="group flex w-40 shrink-0 flex-col overflow-hidden rounded-xl border bg-card transition-shadow hover:shadow-lg"
                                            >
                                                <div className="flex h-24 items-center justify-center bg-gradient-to-br from-primary/5 to-primary/15">
                                                    <FileTextIcon className="text-primary/40 size-10" />
                                                </div>
                                                <div className="flex items-start justify-between p-3">
                                                    <div className="min-w-0 flex-1">
                                                        <p className="truncate text-xs font-medium">
                                                            {titleOfThread(thread)}
                                                        </p>
                                                        {thread.updated_at && (
                                                            <p className="text-muted-foreground mt-0.5 text-[10px]">
                                                                {formatTimeAgo(thread.updated_at)}
                                                            </p>
                                                        )}
                                                    </div>
                                                    <button
                                                        className="text-muted-foreground hover:text-foreground shrink-0 opacity-0 transition group-hover:opacity-100"
                                                        onClick={(e) => e.preventDefault()}
                                                    >
                                                        <MoreVerticalIcon className="size-3.5" />
                                                    </button>
                                                </div>
                                            </Link>
                                        ))}
                                    </div>
                                    <ScrollBar orientation="horizontal" />
                                </ScrollArea>
                            </div>
                        </section>
                    )}

                    {/* Templates */}
                    <section className="px-6 pb-12">
                        <div className="mx-auto max-w-6xl">
                            <h2 className="pb-3 text-lg font-semibold">Templates</h2>
                            <ScrollArea className="w-full">
                                <div className="flex gap-4 pb-4">
                                    {TEMPLATES.map((template) => (
                                        <TemplateCard
                                            key={template.id}
                                            template={template}
                                            onClick={() => handleTemplateClick(template)}
                                        />
                                    ))}
                                </div>
                                <ScrollBar orientation="horizontal" />
                            </ScrollArea>
                        </div>
                    </section>
                </div>
            </WorkspaceBody>
        </WorkspaceContainer>
    );
}
