"use client";

import Link from "next/link";
import {
  useEffect,
  useRef,
  type ComponentProps,
  type KeyboardEvent,
  type MouseEvent,
  type ReactNode,
  type RefObject,
} from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import { PanelEmpty } from "./empty";
import { Search } from "./search";
import { FormSelect } from "./select";
import {
  workspaceIndexListPanelClass,
  workspacePageInsetXClass,
} from "./styles";

export function dotSeparatedMeta(items: ReactNode[]): ReactNode[] {
  const nodes = items.filter(Boolean);
  return nodes.flatMap((node, i, arr) =>
    i < arr.length - 1
      ? [
          node,
          <span key={`dot-sep-${i}`} className="text-border">
            ·
          </span>,
        ]
      : [node],
  );
}

export function ItemListPanel({
  title,
  countLabel,
  toolbar,
  children,
  footer,
  className,
}: {
  title: ReactNode;
  countLabel?: ReactNode;
  toolbar?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  className?: string;
}) {
  return (
    <section
      className={cn(
        "bg-card/80 flex min-h-0 w-full min-w-0 flex-col overflow-hidden rounded-xl border",
        workspaceIndexListPanelClass,
        className,
      )}
    >
      <div
        className={cn(
          "border-border/50 flex shrink-0 items-center justify-between gap-3 border-b py-2",
          workspacePageInsetXClass,
        )}
      >
        <div className="flex min-w-0 shrink items-baseline gap-2">
          <h2 className="text-xs font-semibold tracking-tight sm:text-sm sm:font-medium">
            {title}
          </h2>
          {countLabel != null ? (
            <span className="text-muted-foreground text-[11px] tabular-nums sm:text-xs">
              {countLabel}
            </span>
          ) : null}
        </div>
        {toolbar ? (
          <div className="flex min-w-0 flex-1 items-center justify-end gap-2 overflow-x-auto">
            {toolbar}
          </div>
        ) : null}
      </div>
      <div className="flex min-h-0 flex-1 flex-col">{children}</div>
      {footer ? <div className="shrink-0">{footer}</div> : null}
    </section>
  );
}

const itemRowActionStopPropagation = {
  onClick: (e: MouseEvent) => e.stopPropagation(),
  onKeyDown: (e: KeyboardEvent) => e.stopPropagation(),
} as const;

function ItemRowActionsWrap({ children }: { children: ReactNode }) {
  return (
    <div
      className="flex shrink-0 items-center gap-1.5"
      {...itemRowActionStopPropagation}
    >
      {children}
    </div>
  );
}

export function ItemRowTitle({
  children,
  className,
  href,
}: {
  children: ReactNode;
  className?: string;
  href?: string;
}) {
  return (
    <div className={cn("min-w-0 truncate text-sm font-medium", className)}>
      {href ? (
        <Link
          href={href}
          className="hover:text-foreground block min-w-0 truncate hover:underline focus-visible:underline focus-visible:outline-none"
        >
          {children}
        </Link>
      ) : (
        children
      )}
    </div>
  );
}

export function ItemRowSubtitle({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "text-muted-foreground flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-xs",
        className,
      )}
    >
      {children}
    </div>
  );
}

export function ItemRowMeta({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "text-muted-foreground flex min-w-0 flex-wrap items-center gap-1.5 text-[11px] leading-none tabular-nums",
        className,
      )}
    >
      {children}
    </div>
  );
}

type ItemRowInteractive = {
  href?: string;
  onClick?: () => void;
  className?: string;
  selected?: boolean;
  "data-testid"?: string;
};

export type ItemRowFlushProps = ItemRowInteractive & {
  variant: "flush";
  topStart: ReactNode;
  topEnd?: ReactNode;
  bottomStart?: ReactNode;
  bottomEnd?: ReactNode;
};

type ItemRowFlushLegacyProps = ItemRowInteractive & {
  variant: "flush";
  title: ReactNode;
  titleTrailing?: ReactNode;
  description?: ReactNode;
  meta?: ReactNode;
  badges?: ReactNode;
  actions?: ReactNode;
  topStart?: never;
};

type ItemRowCardProps = ItemRowInteractive & {
  variant?: "card";
  title: ReactNode;
  titleTrailing?: ReactNode;
  description?: ReactNode;
  meta?: ReactNode;
  badges?: ReactNode;
  actions?: ReactNode;
  topStart?: never;
};

export type ItemRowProps =
  | ItemRowFlushProps
  | ItemRowFlushLegacyProps
  | ItemRowCardProps;

function ItemRowFlushBody({
  topStart,
  topEnd,
  bottomStart,
  bottomEnd,
}: Pick<
  ItemRowFlushProps,
  "topStart" | "topEnd" | "bottomStart" | "bottomEnd"
>) {
  const hasBottom = Boolean(bottomStart ?? bottomEnd);

  return (
    <>
      <div className="flex w-full min-w-0 items-center gap-x-2 overflow-hidden">
        <div className="min-w-0 flex-1 space-y-0.5">{topStart}</div>
        {topEnd ? (
          <div className="text-muted-foreground flex min-w-0 shrink items-center gap-x-2">
            {topEnd}
          </div>
        ) : null}
      </div>
      {hasBottom ? (
        <div className="flex w-full min-w-0 items-center gap-x-2 gap-y-1">
          {bottomStart ? (
            <div className="min-w-0 flex-1">{bottomStart}</div>
          ) : (
            <div className="min-w-0 flex-1" aria-hidden />
          )}
          {bottomEnd ? (
            <div className="ml-auto shrink-0">
              <ItemRowActionsWrap>{bottomEnd}</ItemRowActionsWrap>
            </div>
          ) : null}
        </div>
      ) : null}
    </>
  );
}

function flushSlotsFromLegacy(props: ItemRowFlushLegacyProps) {
  const topStart = (
    <>
      <ItemRowTitle>{props.title}</ItemRowTitle>
      {props.description ? (
        <ItemRowSubtitle>{props.description}</ItemRowSubtitle>
      ) : null}
    </>
  );
  const topEnd =
    props.titleTrailing || props.badges ? (
      <>
        {props.titleTrailing}
        {props.badges}
      </>
    ) : undefined;
  const bottomStart = props.meta ? (
    <ItemRowMeta>{props.meta}</ItemRowMeta>
  ) : undefined;
  const bottomEnd = props.actions;

  return { topStart, topEnd, bottomStart, bottomEnd };
}

function ItemRowFlushWithHref({
  href,
  topStart,
  topEnd,
  bottomStart,
  bottomEnd,
  className,
  selected,
  "data-testid": dataTestId,
}: ItemRowFlushProps & { href: string }) {
  const rowClass = cn(
    "group/row flex w-full min-w-0 flex-col gap-1 text-left transition-colors",
    "hover:bg-muted/40 py-2",
    workspacePageInsetXClass,
    selected && "bg-primary/5 ring-primary/20 ring-1",
    className,
  );

  const linkClass =
    "hover:text-foreground min-w-0 rounded-sm focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-ring";

  return (
    <div data-testid={dataTestId} className={rowClass}>
      <div className="flex w-full min-w-0 items-center gap-x-2 overflow-hidden">
        <Link
          href={href}
          className={cn(linkClass, "min-w-0 flex-1 space-y-0.5")}
        >
          {topStart}
        </Link>
        {topEnd ? (
          <Link href={href} className={cn(linkClass, "shrink-0")}>
            {topEnd}
          </Link>
        ) : null}
      </div>
      {(bottomStart ?? bottomEnd) ? (
        <div className="flex w-full min-w-0 items-center gap-x-2 gap-y-1">
          {bottomStart ? (
            <Link href={href} className={cn(linkClass, "min-w-0 flex-1")}>
              {bottomStart}
            </Link>
          ) : (
            <div className="min-w-0 flex-1" aria-hidden />
          )}
          {bottomEnd ? (
            <div className="ml-auto shrink-0">
              <ItemRowActionsWrap>{bottomEnd}</ItemRowActionsWrap>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

export function ItemRow(props: ItemRowProps) {
  const {
    href,
    onClick,
    className,
    selected,
    "data-testid": dataTestId,
    variant = "card",
  } = props;

  const interactive = Boolean(onClick ?? href);
  const Wrapper = href ? "a" : onClick ? "button" : "div";
  const wrapperProps = href
    ? { href }
    : onClick
      ? { type: "button" as const, onClick }
      : {};

  const isFlush = variant === "flush";

  if (isFlush) {
    const slots =
      "topStart" in props && props.topStart != null
        ? {
            topStart: props.topStart,
            topEnd: props.topEnd,
            bottomStart: props.bottomStart,
            bottomEnd: props.bottomEnd,
          }
        : flushSlotsFromLegacy(props as ItemRowFlushLegacyProps);

    if (href) {
      return (
        <ItemRowFlushWithHref
          href={href}
          variant="flush"
          selected={selected}
          className={className}
          data-testid={dataTestId}
          {...slots}
        />
      );
    }

    return (
      <Wrapper
        {...wrapperProps}
        data-testid={dataTestId}
        className={cn(
          "group/row flex w-full min-w-0 flex-col gap-1 text-left transition-colors",
          "hover:bg-muted/40 py-2",
          workspacePageInsetXClass,
          interactive && "cursor-pointer",
          selected && "bg-primary/5 ring-primary/20 ring-1",
          className,
        )}
      >
        <ItemRowFlushBody {...slots} />
      </Wrapper>
    );
  }

  const { title, titleTrailing, description, meta, badges, actions } =
    props as ItemRowCardProps;

  const actionSlot = actions ? (
    <ItemRowActionsWrap>{actions}</ItemRowActionsWrap>
  ) : null;

  const titleLine = (
    <div className="flex w-full min-w-0 items-center gap-x-2 overflow-hidden">
      <div className="min-w-0 flex-1 truncate text-[15px] font-semibold tracking-tight">
        {title}
      </div>
      {titleTrailing ? (
        <div className="text-muted-foreground min-w-0 shrink">
          {titleTrailing}
        </div>
      ) : null}
      {badges}
    </div>
  );

  const bodyBelowTitle = (
    <>
      {description ? (
        <div className="text-muted-foreground line-clamp-2 min-w-0 text-sm leading-snug">
          {description}
        </div>
      ) : null}
      {meta ? (
        <div className="text-muted-foreground flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs tabular-nums">
          {meta}
        </div>
      ) : null}
    </>
  );

  return (
    <Wrapper
      {...wrapperProps}
      data-testid={dataTestId}
      className={cn(
        "group/row flex w-full min-w-0 flex-col gap-2 text-left transition-colors sm:flex-row sm:items-center sm:gap-4",
        "gap-3 rounded-xl px-4 py-3.5 sm:gap-4",
        interactive &&
          "hover:bg-muted/50 focus-visible:ring-ring cursor-pointer focus-visible:ring-[3px] focus-visible:outline-none",
        selected && "bg-primary/5 ring-primary/20 ring-1",
        className,
      )}
    >
      <div className="min-w-0 flex-1 space-y-1">
        {titleLine}
        {bodyBelowTitle}
      </div>
      {actionSlot ? (
        <div className="shrink-0 sm:ml-auto">{actionSlot}</div>
      ) : null}
    </Wrapper>
  );
}

export type WorkspaceIndexListSearch = {
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  /** Opt-in — do not enable on every index page by default. */
  autoFocus?: boolean;
};

export type WorkspaceIndexListPagination = {
  hasNextPage: boolean;
  isFetchingNextPage: boolean;
  onLoadMore: () => void | Promise<unknown>;
  loadMoreLabel: string;
  loadMoreSearchLabel?: string;
  loadingLabel: string;
  loadMoreTestId?: string;
  sentinelTestId?: string;
  listLength?: number;
};

export function WorkspaceIndexList({
  title,
  countLabel,
  search,
  toolbar,
  pagination,
  footer,
  className,
  isLoading,
  loadingLabel,
  isEmpty,
  empty,
  isSearchEmpty = false,
  searchEmpty,
  listTestId,
  listProps,
  emptyAlign = "center",
  emptyClassName,
  children,
}: {
  title: ReactNode;
  countLabel?: ReactNode;
  search?: WorkspaceIndexListSearch;
  toolbar?: ReactNode;
  pagination?: WorkspaceIndexListPagination;
  footer?: ReactNode;
  className?: string;
  isLoading?: boolean;
  loadingLabel?: string;
  isEmpty: boolean;
  empty: ReactNode;
  isSearchEmpty?: boolean;
  searchEmpty?: ReactNode;
  emptyAlign?: "left" | "center";
  emptyClassName?: string;
  listTestId?: string;
  listProps?: Omit<ComponentProps<"div">, "children">;
  children: ReactNode;
}) {
  const isSearching = Boolean(search?.value.trim());
  const sentinelRef = useItemListInfiniteScroll({
    hasNextPage: Boolean(pagination?.hasNextPage),
    isFetchingNextPage: pagination?.isFetchingNextPage ?? false,
    onLoadMore: pagination?.onLoadMore ?? noopLoadMore,
    autoLoad: Boolean(pagination) && !isSearching,
    listLength: pagination?.listLength ?? 0,
  });

  const toolbarNode =
    search || toolbar ? (
      <ListPanelToolbar>
        {search ? (
          <ListSearchField
            value={search.value}
            onChange={search.onChange}
            placeholder={search.placeholder}
            autoFocus={search.autoFocus}
          />
        ) : null}
        {toolbar}
      </ListPanelToolbar>
    ) : undefined;

  const paginationFooter =
    pagination && isSearching ? (
      <ItemListLoadMoreFooter
        hasNextPage={pagination.hasNextPage}
        isFetchingNextPage={pagination.isFetchingNextPage}
        onLoadMore={pagination.onLoadMore}
        loadMoreLabel={pagination.loadMoreLabel}
        loadMoreSearchLabel={pagination.loadMoreSearchLabel}
        loadingLabel={pagination.loadingLabel}
        isSearching
        loadMoreTestId={pagination.loadMoreTestId}
      />
    ) : null;

  const panelFooter =
    paginationFooter || footer ? (
      <>
        {paginationFooter}
        {footer}
      </>
    ) : undefined;

  const showInfiniteTail =
    Boolean(pagination) &&
    !isSearching &&
    !isLoading &&
    !isEmpty &&
    !isSearchEmpty;

  return (
    <ItemListPanel
      title={title}
      countLabel={countLabel}
      toolbar={toolbarNode}
      footer={panelFooter}
      className={cn("min-h-0", className)}
    >
      {isLoading ? (
        <p
          className={cn(
            "text-muted-foreground py-6 text-sm",
            workspacePageInsetXClass,
          )}
        >
          {loadingLabel}
        </p>
      ) : isEmpty ? (
        <PanelEmpty align={emptyAlign} className={emptyClassName}>
          {empty}
        </PanelEmpty>
      ) : isSearchEmpty ? (
        <PanelEmpty align={emptyAlign} className={emptyClassName}>
          {searchEmpty}
        </PanelEmpty>
      ) : (
        <>
          <ItemList variant="flush" data-testid={listTestId} {...listProps}>
            {children}
          </ItemList>
          {showInfiniteTail ? (
            <ItemListInfiniteTail
              sentinelRef={sentinelRef}
              isFetchingNextPage={pagination?.isFetchingNextPage}
              loadingLabel={pagination?.loadingLabel}
              sentinelTestId={pagination?.sentinelTestId}
            />
          ) : null}
        </>
      )}
    </ItemListPanel>
  );
}

export function ItemList({
  children,
  className,
  variant = "card",
  ...props
}: {
  children: ReactNode;
  className?: string;
  variant?: "card" | "flush";
} & ComponentProps<"div">) {
  return (
    <div
      className={cn(
        variant === "flush"
          ? "[&>*]:border-border/50 flex flex-col [&>*]:border-b"
          : "divide-border/60 flex flex-col divide-y px-1 py-1 sm:px-2",
        className,
      )}
      {...props}
    >
      {children}
    </div>
  );
}

export function ListPanelToolbar({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex w-full min-w-0 flex-nowrap items-center justify-stretch gap-2 sm:justify-end",
        className,
      )}
    >
      {children}
    </div>
  );
}

export function ListSearchField({
  className,
  ...props
}: ComponentProps<typeof Search>) {
  return (
    <Search
      className={cn(
        "max-w-44 min-w-[7.5rem] shrink-0 sm:w-44 sm:max-w-none",
        className,
      )}
      {...props}
    />
  );
}

function ListFilterSelect({
  className,
  ...props
}: ComponentProps<typeof FormSelect>) {
  return (
    <FormSelect
      appearance="toolbar"
      size="sm"
      className={cn("w-full", className)}
      {...props}
    />
  );
}

export function ListFilterField({
  className,
  "data-testid": dataTestId,
  ...selectProps
}: ComponentProps<typeof ListFilterSelect> & {
  "data-testid"?: string;
}) {
  return (
    <div
      className={cn("w-[7.25rem] shrink-0 sm:w-32", className)}
      data-testid={dataTestId}
    >
      <ListFilterSelect {...selectProps} />
    </div>
  );
}

function noopLoadMore(): void {
  return;
}

function useItemListInfiniteScroll({
  hasNextPage,
  isFetchingNextPage,
  onLoadMore,
  autoLoad = true,
  listLength = 0,
}: {
  hasNextPage: boolean;
  isFetchingNextPage: boolean;
  onLoadMore: () => void | Promise<unknown>;
  autoLoad?: boolean;
  listLength?: number;
}) {
  const sentinelRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const element = sentinelRef.current;
    if (!element || !hasNextPage || !autoLoad) {
      return;
    }
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry?.isIntersecting && hasNextPage && !isFetchingNextPage) {
          void onLoadMore();
        }
      },
      { rootMargin: "200px 0px 200px 0px" },
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, [autoLoad, hasNextPage, isFetchingNextPage, listLength, onLoadMore]);

  return sentinelRef;
}

function ItemListInfiniteTail({
  sentinelRef,
  isFetchingNextPage,
  loadingLabel,
  sentinelTestId,
}: {
  sentinelRef: RefObject<HTMLDivElement | null>;
  isFetchingNextPage?: boolean;
  loadingLabel?: string;
  sentinelTestId?: string;
}) {
  return (
    <>
      {isFetchingNextPage && loadingLabel ? (
        <p className="text-muted-foreground px-4 py-3 text-center text-xs">
          {loadingLabel}
        </p>
      ) : null}
      <div
        ref={sentinelRef}
        className="h-px shrink-0"
        aria-hidden
        data-testid={sentinelTestId}
      />
    </>
  );
}

function ItemListLoadMoreFooter({
  hasNextPage,
  isFetchingNextPage,
  onLoadMore,
  loadMoreLabel,
  loadMoreSearchLabel,
  loadingLabel,
  isSearching = false,
  className,
  loadMoreTestId,
}: {
  hasNextPage: boolean;
  isFetchingNextPage: boolean;
  onLoadMore: () => void | Promise<unknown>;
  loadMoreLabel: string;
  loadMoreSearchLabel?: string;
  loadingLabel: string;
  isSearching?: boolean;
  className?: string;
  loadMoreTestId?: string;
}) {
  if (!hasNextPage) {
    return null;
  }
  const label = isFetchingNextPage
    ? loadingLabel
    : isSearching && loadMoreSearchLabel
      ? loadMoreSearchLabel
      : loadMoreLabel;

  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      className={cn("w-full rounded-none border-0 border-t", className)}
      disabled={isFetchingNextPage}
      onClick={() => void onLoadMore()}
      data-testid={loadMoreTestId}
    >
      {label}
    </Button>
  );
}

export function formatItemListCountLabel(options: {
  shownCount: number;
  loadedCount: number;
  hasNextPage: boolean;
  isFiltering: boolean;
}): string {
  const { shownCount, loadedCount, hasNextPage, isFiltering } = options;
  if (isFiltering && shownCount !== loadedCount) {
    return `${shownCount} / ${loadedCount}`;
  }
  if (hasNextPage && !isFiltering) {
    return `${shownCount}+`;
  }
  return String(shownCount);
}
