"use client";

import {
    ChevronRightIcon,
    MonitorIcon,
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
}

const TEMPLATES: Template[] = [
    {
        id: "business-pitch",
        name: "Business Pitch",
        description: "Investor-ready pitch deck",
        prompt: "Create a 7-slide business pitch deck about an AI-powered customer analytics platform. Include title slide, problem, solution, market opportunity, business model, traction, and team slides. Use a dark-premium style with blue accents.",
        colors: ["#2563eb", "#1e40af", "#0ea5e9"],
    },
    {
        id: "product-launch",
        name: "Product Launch",
        description: "Product announcement presentation",
        prompt: "Create a 5-slide product launch presentation in keynote style for a new wearable AI device. Include title, key features, demo screenshots concept, pricing, and call to action.",
        colors: ["#0a0a0a", "#e5e5e5", "#f59e0b"],
    },
    {
        id: "team-update",
        name: "Team Update",
        description: "Weekly team status update",
        prompt: "Create a 4-slide weekly team update presentation. Include this week's highlights, key metrics (with charts), blockers, and next week's priorities. Use minimal-swiss style with green accents.",
        colors: ["#059669", "#10b981", "#34d399"],
    },
    {
        id: "educational",
        name: "Course Lecture",
        description: "Educational slide deck",
        prompt: "Create a 6-slide educational presentation about 'Introduction to Machine Learning'. Cover: what is ML, types (supervised, unsupervised, reinforcement), common algorithms, real-world applications, getting started. Use editorial style.",
        colors: ["#7c3aed", "#8b5cf6", "#a78bfa"],
    },
    {
        id: "quarterly-review",
        name: "Quarterly Review",
        description: "Q4 business review deck",
        prompt: "Create a 5-slide quarterly business review. Include executive summary, revenue performance (with bar chart data), customer growth metrics, key achievements, and Q1 goals. Use glassmorphism style.",
        colors: ["#06b6d4", "#3b82f6", "#8b5cf6"],
    },
    {
        id: "creative-portfolio",
        name: "Creative Portfolio",
        description: "Portfolio showcase deck",
        prompt: "Create a 5-slide creative portfolio presentation showcasing a design agency's work. Include about us, featured projects, services, client testimonials, and contact. Use gradient-modern style with vibrant colors.",
        colors: ["#ec4899", "#f97316", "#eab308"],
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
                <MonitorIcon className="size-10" style={{ color: template.colors[0], opacity: 0.5 }} />
            </div>
            <div className="p-3">
                <p className="text-left text-xs font-medium">{template.name}</p>
                <p className="text-left text-[10px] text-muted-foreground mt-0.5">{template.description}</p>
            </div>
        </button>
    );
}

export default function PresentationsHomePage() {
    const { t } = useI18n();
    const router = useRouter();
    const { data: threads } = useThreads();
    const [prompt, setPrompt] = useState("");

    useEffect(() => {
        document.title = `Presentations - ${t.pages.appName}`;
    }, [t.pages.appName]);

    const handleSubmit = useCallback(
        (text?: string) => {
            const msg = text ?? prompt;
            if (!msg.trim()) return;
            sessionStorage.setItem("presentations-initial-prompt", msg);
            router.push("/workspace/presentations/new");
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
                            <MonitorIcon className="size-6" />
                            <span>What presentation would you like to create?</span>
                        </div>

                        <div className="mt-6 w-full">
                            <div className="flex items-center gap-2 rounded-xl border bg-card px-4 py-3 shadow-sm focus-within:ring-2 focus-within:ring-primary/20">
                                <input
                                    className="min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
                                    placeholder="Describe your presentation..."
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

                    {/* Recent Projects */}
                    {threads && threads.length > 0 && (
                        <section className="px-6 pb-6">
                            <div className="mx-auto max-w-6xl">
                                <div className="flex items-center justify-between pb-3">
                                    <h2 className="text-lg font-semibold">Recent Presentations</h2>
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
                                                href={`/workspace/presentations/${thread.thread_id}`}
                                                className="group flex w-40 shrink-0 flex-col overflow-hidden rounded-xl border bg-card transition-shadow hover:shadow-lg"
                                            >
                                                <div className="flex h-24 items-center justify-center bg-gradient-to-br from-primary/5 to-primary/15">
                                                    <MonitorIcon className="text-primary/40 size-10" />
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
