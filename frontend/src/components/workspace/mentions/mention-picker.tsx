"use client";

import {
  CheckIcon,
  FileIcon,
  MessagesSquareIcon,
  SparklesIcon,
  UploadIcon,
  XIcon,
} from "lucide-react";
import {
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type Ref,
} from "react";

import type { ConversationReference } from "@/core/conversation-references";
import { useI18n } from "@/core/i18n/hooks";
import { useInfiniteProjectDocuments } from "@/core/projects/hooks";
import type { ProjectDocument } from "@/core/projects/types";
import type { Skill } from "@/core/skills/type";
import { useInfiniteThreads } from "@/core/threads/hooks";
import { agentNameOfThread, titleOfThread } from "@/core/threads/utils";
import { isCompositionConfirmEnter, isIMEComposing } from "@/lib/ime";
import { cn } from "@/lib/utils";

import { MAX_EXPLICIT_SKILLS } from "./inline-references";

export type MentionSelection =
  | { kind: "skill"; skill: Skill }
  | { kind: "file"; document: ProjectDocument }
  | { kind: "conversation"; reference: ConversationReference }
  | { kind: "upload" };
export type MentionPickerHandle = {
  onKeyDown: (event: KeyboardEvent<HTMLElement>) => void;
};
type Option = {
  id: string;
  label: string;
  description?: string;
  selection: MentionSelection;
  disabled?: boolean;
  selected?: boolean;
};

export function MentionPicker({
  ref,
  query,
  searchInput = false,
  skills,
  skillsLoading = false,
  skillsError,
  onRetrySkills,
  capability,
  onActiveOptionChange,
  selectedSkills,
  references,
  threadId,
  projectId,
  busy,
  error,
  onSelect,
  onClose,
  listId,
}: {
  ref?: Ref<MentionPickerHandle>;
  query: string;
  searchInput?: boolean;
  skills: Skill[];
  skillsLoading?: boolean;
  skillsError?: unknown;
  onRetrySkills?: () => unknown;
  capability: { enabled: boolean; maxReferences: number; isLoading: boolean };
  onActiveOptionChange?: (id: string | undefined) => void;
  selectedSkills?: string[];
  references: ConversationReference[];
  threadId: string;
  projectId?: string | null;
  busy: boolean;
  error: string | null;
  onSelect: (selection: MentionSelection) => void;
  onClose: () => void;
  listId: string;
}) {
  const { t } = useI18n();
  const labels = t.inputBox;
  const documents = useInfiniteProjectDocuments(projectId ?? "", {
    enabled: !!projectId,
  });
  const conversations = useInfiniteThreads(undefined, {
    enabled: capability.enabled,
  });
  const [search, setSearch] = useState("");
  const [activeId, setActiveId] = useState<string | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const compositionEndedAt = useRef(-Infinity);
  const filter = (searchInput ? search : query).toLocaleLowerCase();
  const options = useMemo(() => {
    const result: Option[] = skills
      .filter((skill) => skill.enabled)
      .map((skill) => ({
        id: `skill:${skill.name}`,
        label: skill.name,
        description: skill.description,
        selection: { kind: "skill", skill },
        selected: selectedSkills?.includes(skill.name),
        disabled:
          !selectedSkills?.includes(skill.name) &&
          new Set(selectedSkills).size >= MAX_EXPLICIT_SKILLS,
      }));
    for (const document of documents.data?.pages.flatMap(
      (page) => page.documents,
    ) ?? []) {
      result.push({
        id: `file:${document.id}`,
        label: document.name,
        description: document.content_missing
          ? labels.mentionUnavailable
          : undefined,
        selection: { kind: "file", document },
        disabled: document.content_missing,
      });
    }
    if (capability.enabled) {
      const seen = new Set<string>();
      for (const thread of conversations.data?.pages.flat() ?? []) {
        if (thread.thread_id === threadId || seen.has(thread.thread_id))
          continue;
        seen.add(thread.thread_id);
        const selected = references.some(
          (item) => item.threadId === thread.thread_id,
        );
        result.push({
          id: `conversation:${thread.thread_id}`,
          label: titleOfThread(thread),
          selection: {
            kind: "conversation",
            reference: {
              threadId: thread.thread_id,
              title: titleOfThread(thread),
              agentName: agentNameOfThread(thread),
            },
          },
          selected,
          disabled: !selected && references.length >= capability.maxReferences,
        });
      }
    }
    const filtered = result.filter((option) =>
      `${option.label} ${option.description ?? ""}`
        .toLocaleLowerCase()
        .includes(filter),
    );
    filtered.push({
      id: "upload",
      label: labels.mentionUpload,
      selection: { kind: "upload" },
    });
    return filtered;
  }, [
    skills,
    selectedSkills,
    documents.data,
    conversations.data,
    capability.enabled,
    capability.maxReferences,
    threadId,
    references,
    filter,
    labels,
  ]);
  const available = options.filter((option) => !option.disabled);
  const active =
    available.find((option) => option.id === activeId) ??
    (filter
      ? available.find((option) => option.selection.kind !== "upload")
      : available[0]);
  const optionId = (id: string) => `${listId}-${encodeURIComponent(id)}`;
  const activeOptionId = active ? optionId(active.id) : undefined;
  useEffect(() => {
    onActiveOptionChange?.(searchInput ? undefined : activeOptionId);
  }, [activeOptionId, searchInput, onActiveOptionChange]);
  useEffect(
    () => () => onActiveOptionChange?.(undefined),
    [onActiveOptionChange],
  );
  const choose = (option: Option) => {
    if (!busy && !option.disabled) onSelect(option.selection);
  };
  const onKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (isCompositionConfirmEnter(event, compositionEndedAt.current)) {
      event.preventDefault();
      return;
    }
    if (isIMEComposing(event)) return;
    if (event.key === "Escape") {
      event.preventDefault();
      onClose();
      return;
    }
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const index = available.findIndex((option) => option.id === active?.id);
      const next =
        available[
          (index + (event.key === "ArrowDown" ? 1 : -1) + available.length) %
            available.length
        ];
      setActiveId(next?.id ?? null);
    } else if (event.key === "Enter" && !event.shiftKey && active) {
      event.preventDefault();
      choose(active);
    }
  };
  useImperativeHandle(ref, () => ({ onKeyDown }));
  useEffect(() => {
    if (activeOptionId)
      document
        .getElementById(activeOptionId)
        ?.scrollIntoView?.({ block: "nearest" });
  }, [activeOptionId]);
  const loading =
    skillsLoading ||
    capability.isLoading ||
    (!!projectId && documents.isPending) ||
    (capability.enabled && conversations.isPending);
  const failed =
    !!skillsError ||
    (!!projectId && documents.isError) ||
    (capability.enabled && conversations.isError);
  const groups = [
    { kind: "skill", title: labels.mentionSkills, Icon: SparklesIcon },
    { kind: "file", title: labels.mentionFiles, Icon: FileIcon },
    {
      kind: "conversation",
      title: labels.mentionConversations,
      Icon: MessagesSquareIcon,
    },
    { kind: "upload", title: "", Icon: UploadIcon },
  ] as const;
  return (
    <div
      ref={rootRef}
      className="bg-popover text-popover-foreground border-border rounded-xl border p-2 shadow-lg"
      data-testid="mention-picker"
    >
      <div className="flex items-center gap-2 px-2 pb-2">
        {searchInput ? (
          <input
            aria-label={labels.mentionSearch}
            autoFocus
            className="min-w-0 flex-1 bg-transparent text-sm outline-none"
            role="combobox"
            aria-expanded="true"
            aria-controls={listId}
            aria-activedescendant={activeOptionId}
            aria-autocomplete="list"
            placeholder={labels.mentionSearch}
            value={search}
            onChange={(event) => {
              setSearch(event.target.value);
              setActiveId(null);
            }}
            onKeyDown={onKeyDown}
            onCompositionEnd={() => {
              compositionEndedAt.current = Date.now();
            }}
          />
        ) : (
          <span className="flex-1 text-sm font-medium">
            {labels.mentionPicker}
          </span>
        )}
        <button
          type="button"
          aria-label={labels.mentionClose}
          onClick={onClose}
        >
          <XIcon className="size-4" />
        </button>
      </div>
      <div
        id={listId}
        role="listbox"
        aria-multiselectable="true"
        aria-label={labels.mentionPicker}
        aria-busy={busy || loading}
        className="max-h-72 overflow-y-auto"
      >
        {groups.map(({ kind, title, Icon }) => {
          const items = options.filter(
            (option) => option.selection.kind === kind,
          );
          if (!items.length) return null;
          return (
            <div
              key={kind}
              role="group"
              aria-label={title || labels.mentionUpload}
            >
              {title && (
                <div className="text-muted-foreground px-2 py-1 text-xs">
                  {title}
                </div>
              )}
              {items.map((option) => (
                <button
                  key={option.id}
                  type="button"
                  role="option"
                  id={optionId(option.id)}
                  aria-selected={option.selected === true}
                  aria-disabled={busy || option.disabled}
                  disabled={busy || option.disabled}
                  onMouseDown={(event) => event.preventDefault()}
                  onMouseEnter={() => setActiveId(option.id)}
                  onClick={() => choose(option)}
                  className={cn(
                    "flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left text-sm disabled:opacity-40",
                    active?.id === option.id &&
                      "bg-accent text-accent-foreground",
                  )}
                >
                  <Icon className="size-4 shrink-0" />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate">{option.label}</span>
                    {option.description && (
                      <span className="text-muted-foreground block truncate text-xs">
                        {option.description}
                      </span>
                    )}
                  </span>
                  {option.selected && <CheckIcon className="size-4 shrink-0" />}
                </button>
              ))}
            </div>
          );
        })}
      </div>
      {options.length === 1 && !loading && !failed && (
        <p className="text-muted-foreground px-2 py-2 text-xs">
          {labels.mentionEmpty}
        </p>
      )}
      {loading && (
        <p role="status" className="px-2 py-2 text-xs">
          {labels.mentionLoading}
        </p>
      )}
      {failed && (
        <div role="alert" className="px-2 text-xs">
          {labels.mentionFailed}{" "}
          <button
            type="button"
            onClick={() => {
              if (skillsError) void onRetrySkills?.();
              if (projectId && documents.isError) void documents.refetch();
              if (capability.enabled && conversations.isError)
                void conversations.refetch();
            }}
          >
            {labels.mentionRetry}
          </button>
        </div>
      )}
      {(documents.hasNextPage ||
        (capability.enabled && conversations.hasNextPage)) && (
        <button
          type="button"
          className="px-2 py-2 text-xs underline"
          disabled={
            documents.isFetchingNextPage || conversations.isFetchingNextPage
          }
          onClick={() => {
            if (documents.hasNextPage) void documents.fetchNextPage();
            if (capability.enabled && conversations.hasNextPage)
              void conversations.fetchNextPage();
          }}
        >
          {labels.mentionLoadMore}
        </button>
      )}
      {!projectId && (
        <p className="text-muted-foreground px-2 py-1 text-xs">
          {labels.mentionNoProject}
        </p>
      )}
      <p className="text-muted-foreground px-2 py-1 text-xs">
        {labels.mentionMultipleSkills}
      </p>
      {capability.enabled && (
        <p className="text-muted-foreground px-2 py-1 text-xs">
          {labels.referenceConversationsLimit(capability.maxReferences)}
        </p>
      )}
      {busy && (
        <p role="status" className="px-2 py-1 text-xs">
          {labels.mentionAttaching}
        </p>
      )}
      {error && (
        <p role="alert" className="text-destructive px-2 py-1 text-xs">
          {error}
        </p>
      )}
    </div>
  );
}
