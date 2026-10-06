"use client";

import { X } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import {
  EmptyState,
  NewTaskButton,
} from "@/components/workspace/scheduled-tasks/empty-state";
import { SchedulerStateNotice } from "@/components/workspace/scheduled-tasks/scheduler-state-notice";
import {
  statusTabOf,
  type StatusTab,
} from "@/components/workspace/scheduled-tasks/shared";
import { TaskDetail } from "@/components/workspace/scheduled-tasks/task-detail";
import {
  TaskFormDialog,
  type TaskFormRequest,
} from "@/components/workspace/scheduled-tasks/task-form-dialog";
import { TaskList } from "@/components/workspace/scheduled-tasks/task-list";
import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import { useScheduledTasksFeature } from "@/core/features/hooks";
import { useI18n } from "@/core/i18n/hooks";
import { describeScheduledTaskError } from "@/core/scheduled-tasks/errors";
import {
  useScheduledTasks,
  useThreadScheduledTasks,
} from "@/core/scheduled-tasks/hooks";
import { matchesScheduledTaskQuery } from "@/core/scheduled-tasks/search";
import type { ScheduledTask } from "@/core/scheduled-tasks/types";

const TABS: StatusTab[] = ["all", "active", "paused", "finished"];

function inTab(task: ScheduledTask, tab: StatusTab): boolean {
  return tab === "all" || statusTabOf(task) === tab;
}

export default function ScheduledTasksPage() {
  const { t, locale } = useI18n();
  const st = t.scheduledTasks;
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const threadId = searchParams.get("thread_id");
  const taskIdParam = searchParams.get("task_id");
  const feature = useScheduledTasksFeature();
  const createBlocked = !feature.running;

  const allTasksQuery = useScheduledTasks();
  const threadTasksQuery = useThreadScheduledTasks(threadId);
  const query = threadId ? threadTasksQuery : allTasksQuery;
  const tasks: ScheduledTask[] = useMemo(() => query.data ?? [], [query.data]);
  const [tab, setTab] = useState<StatusTab>("all");
  const [search, setSearch] = useState("");
  const [formRequest, setFormRequest] = useState<TaskFormRequest | null>(null);
  const detailRef = useRef<HTMLDivElement>(null);

  const visible = tasks.filter(
    (task) => inTab(task, tab) && matchesScheduledTaskQuery(task, search),
  );
  const selectedTask =
    visible.find((task) => task.id === taskIdParam) ?? visible[0] ?? null;

  useEffect(() => {
    document.title = `${t.sidebar.scheduledTasks} - ${t.pages.appName}`;
  }, [t.pages.appName, t.sidebar.scheduledTasks]);

  // A deep link (`?task_id=`) to a task the current tab or search hides shows
  // it anyway: switch to "All" and clear the search, once per link.
  const appliedLink = useRef<string | null>(null);
  useEffect(() => {
    if (!taskIdParam || appliedLink.current === taskIdParam) return;
    const target = tasks.find((task) => task.id === taskIdParam);
    if (!target) return;
    appliedLink.current = taskIdParam;
    if (!inTab(target, tab)) setTab("all");
    if (!matchesScheduledTaskQuery(target, search)) setSearch("");
  }, [search, tab, taskIdParam, tasks]);

  const replaceQuery = useCallback(
    (taskId: string | null, { keepThread = true } = {}) => {
      const params = new URLSearchParams();
      if (keepThread && threadId) params.set("thread_id", threadId);
      if (taskId) params.set("task_id", taskId);
      const qs = params.toString();
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    },
    [pathname, router, threadId],
  );

  const selectTask = (taskId: string) => {
    appliedLink.current = taskId;
    replaceQuery(taskId);
    // Below `lg` the detail sits under the list: bring it into view.
    if (
      typeof window !== "undefined" &&
      !window.matchMedia?.("(min-width: 1024px)").matches
    ) {
      requestAnimationFrame(() =>
        detailRef.current?.scrollIntoView({
          behavior: "smooth",
          block: "start",
        }),
      );
    }
  };

  const openCreate = () => setFormRequest({ mode: "create" });
  const tabCount = (value: StatusTab) =>
    tasks.filter((task) => inTab(task, value)).length;
  // The empty state is about the user's tasks, not this chat's: a chat with
  // no tasks of its own shows the (empty) filtered list instead.
  const isEmpty =
    allTasksQuery.isSuccess && (allTasksQuery.data ?? []).length === 0;

  return (
    <WorkspaceContainer>
      <WorkspaceHeader />
      <WorkspaceBody>
        <div className="mx-auto flex w-full max-w-6xl min-w-0 flex-col gap-4 px-4 py-5 sm:px-6">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="flex min-w-0 flex-col gap-1">
              <h1 className="text-2xl font-semibold">
                {t.sidebar.scheduledTasks}
              </h1>
              <p className="text-muted-foreground text-sm">
                {feature.toolEnabled
                  ? st.page.description
                  : st.page.descriptionNoChat}
              </p>
            </div>
            {feature.available && (
              <NewTaskButton
                createBlocked={createBlocked}
                onClick={openCreate}
              />
            )}
          </div>

          <SchedulerStateNotice
            available={feature.available}
            running={feature.running}
          />

          {feature.available && (
            <>
              {threadId && (
                <div
                  className="bg-muted/60 flex w-fit items-center gap-2 rounded-full py-1 pr-1 pl-3 text-sm"
                  data-testid="scheduled-task-thread-filter"
                >
                  <span>{st.page.threadFilter}</span>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-7 rounded-full"
                    onClick={() =>
                      replaceQuery(taskIdParam, { keepThread: false })
                    }
                  >
                    <X aria-hidden />
                    {st.page.showAll}
                  </Button>
                </div>
              )}

              {query.error ? (
                <div
                  role="alert"
                  className="text-destructive text-sm"
                  data-testid="scheduled-task-load-error"
                >
                  {st.detail.loadFailed}:{" "}
                  {
                    describeScheduledTaskError(query.error, t, { locale })
                      .message
                  }
                </div>
              ) : null}

              {isEmpty ? (
                <EmptyState
                  toolEnabled={feature.toolEnabled}
                  createBlocked={createBlocked}
                  onCreate={openCreate}
                />
              ) : (
                <div className="grid min-w-0 gap-4 lg:grid-cols-[330px_minmax(0,1fr)] lg:items-start">
                  <div className="flex min-w-0 flex-col gap-3">
                    <ToggleGroup
                      type="single"
                      value={tab}
                      onValueChange={(value) => {
                        if (value) setTab(value as StatusTab);
                      }}
                      aria-label={st.page.tabsLabel}
                      size="sm"
                      spacing={1}
                      className="flex-wrap"
                    >
                      {TABS.map((value) => (
                        <ToggleGroupItem
                          key={value}
                          value={value}
                          className="data-[state=on]:bg-secondary gap-1 rounded-full px-2.5"
                        >
                          {st.page.tabs[value]}
                          <span
                            aria-hidden
                            className="text-muted-foreground tabular-nums"
                          >
                            {tabCount(value)}
                          </span>
                        </ToggleGroupItem>
                      ))}
                    </ToggleGroup>
                    <div className="flex gap-2">
                      <Input
                        type="search"
                        aria-label={st.page.search}
                        placeholder={st.page.search}
                        value={search}
                        onChange={(event) => setSearch(event.target.value)}
                      />
                      {search && (
                        <Button variant="outline" onClick={() => setSearch("")}>
                          {st.search.clear}
                        </Button>
                      )}
                    </div>
                    {query.isSuccess && visible.length === 0 && (
                      <p
                        role="status"
                        data-testid="scheduled-task-search-empty"
                        className="text-muted-foreground text-sm"
                      >
                        {st.search.noResults}
                      </p>
                    )}
                    <TaskList
                      tasks={visible}
                      selectedId={selectedTask?.id ?? null}
                      onSelect={selectTask}
                    />
                  </div>
                  <div ref={detailRef} className="min-w-0 scroll-mt-4">
                    {selectedTask ? (
                      <TaskDetail
                        key={selectedTask.id}
                        task={selectedTask}
                        toolEnabled={feature.toolEnabled}
                        createBlocked={createBlocked}
                        onEdit={(task, focus) =>
                          setFormRequest({ mode: "edit", task, focus })
                        }
                        onDuplicate={(task) =>
                          setFormRequest({ mode: "duplicate", task })
                        }
                        onDeleted={() => replaceQuery(null)}
                      />
                    ) : query.isSuccess ? (
                      <p className="text-muted-foreground rounded-lg border border-dashed p-6 text-center text-sm">
                        {st.page.selectHint}
                      </p>
                    ) : null}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </WorkspaceBody>

      <TaskFormDialog
        request={formRequest}
        toolEnabled={feature.toolEnabled}
        onOpenChange={(open) => {
          if (!open) setFormRequest(null);
        }}
        onSaved={(task, mode) => {
          if (mode !== "edit") {
            appliedLink.current = null;
            replaceQuery(task.id);
          }
        }}
      />
    </WorkspaceContainer>
  );
}
