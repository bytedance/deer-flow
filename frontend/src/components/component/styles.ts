import { cn } from "@/lib/utils";

const textXs = "text-xs leading-none md:text-xs";

export const workspaceControlHeightClass = cn("h-7 min-h-7", textXs);

export const workspaceDialogControlHeightClass = cn("h-8 min-h-8", textXs);

export const workspaceFieldFocusClass =
  "focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px]";

export const workspacePageInsetXClass = "px-2 sm:px-2.5";

export const workspacePageBodyPaddingClass = cn(
  workspacePageInsetXClass,
  "py-2 sm:py-2.5",
);

export const workspacePageBodyGapClass = "gap-3";

export const workspacePageScrollBodyClass = "flex min-h-0 flex-1 flex-col";

export const workspaceGlassHeaderClass =
  "sticky top-0 z-10 shrink-0 border-b border-border/40 bg-background/85 backdrop-blur-md supports-[backdrop-filter]:bg-background/70";

export const workspaceHeaderAccentClass =
  "bg-primary h-5 w-0.5 rounded-full sm:h-6";

export const workspacePageHeaderStripClass =
  "min-h-8 py-1 sm:min-h-9 sm:py-1.5";

export const workspaceIndexListPanelClass = "min-h-0 flex-1";

export const workspaceToolbarSearchInputClass = cn(
  workspaceControlHeightClass,
  "rounded-md border-border/70 bg-transparent shadow-none",
);

export const workspaceToolbarSelectTriggerClass = cn(
  workspaceControlHeightClass,
  "!h-7 min-h-7 rounded-md border-border/70 bg-transparent px-3 py-0 shadow-xs dark:bg-transparent",
  "!text-xs md:!text-xs",
  "[&_[data-slot=select-value]]:line-clamp-1 [&_[data-slot=select-value]]:whitespace-nowrap [&_[data-slot=select-value]]:text-xs",
  "[&_svg:not([class*='size-'])]:size-3",
);

export const panelInteractiveClass = cn(
  "rounded-xl border border-border/50 bg-card/80 shadow-none",
  "hover:border-border/70",
);

export const headerButtonClass =
  "h-7 min-h-7 shrink-0 gap-1 rounded-md border-border/70 bg-transparent px-2.5 text-xs leading-none shadow-none hover:bg-muted/40 sm:px-3";

export const headerCreateEmphasisButtonClass =
  "!border-primary !bg-primary !text-primary-foreground shadow-xs hover:!bg-primary/90 hover:!text-primary-foreground";

const actionGlyphClass =
  "inline-flex shrink-0 items-center justify-center font-extrabold leading-none";

export const headerActionPlusGlyphClass = cn(
  actionGlyphClass,
  "text-xs leading-none tracking-tight",
);

export const dialogFormActionCancelGlyphClass = cn(
  actionGlyphClass,
  "size-4 text-base tracking-tight",
);

export const rowActionIconProps = {
  strokeWidth: 2,
  absoluteStrokeWidth: true,
  className: "size-3.5 shrink-0 sm:size-4",
} as const;

export const toggleClass = "w-fit max-w-full";

export const toggleItemClass = cn(
  workspaceDialogControlHeightClass,
  "shrink-0 px-3",
);

export const dialogFooterButtonClass =
  "box-border w-[5.75rem] shrink-0 justify-center px-2.5 text-xs font-medium";

export const dialogSecondaryButtonClass = cn(
  dialogFooterButtonClass,
  "border-border/70 bg-transparent hover:bg-muted/50",
);

export const destructiveOutlineActionClass =
  "!text-destructive hover:!text-destructive active:!text-destructive [&_svg]:!text-destructive hover:!bg-destructive/10 active:!bg-destructive/15 dark:hover:!bg-destructive/15";

export const dialogDestructiveOutlineButtonClass = cn(
  dialogSecondaryButtonClass,
  destructiveOutlineActionClass,
  "border-destructive/40 shadow-xs",
);

export const dialogFooterClass =
  "shrink-0 justify-center flex-col-reverse gap-2 border-t border-border/40 pt-3 sm:flex-row sm:justify-center";

export const dialogFieldControlClass = cn(
  workspaceDialogControlHeightClass,
  "shadow-xs bg-transparent dark:bg-transparent",
);

export const dialogTextareaControlClass =
  "min-h-8 bg-transparent px-3 py-2 text-xs leading-relaxed shadow-xs dark:bg-transparent";

export const workspaceDialogContentClass =
  "flex max-h-[min(92vh,46rem)] flex-col gap-3 p-4 sm:max-w-[52rem] sm:p-5";

export const workspaceConfirmDialogContentClass =
  "flex flex-col gap-3 p-4 sm:max-w-md sm:p-5";

export const workspaceDialogBodyScrollClass =
  "flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto scroll-pt-2 pt-2 pb-0";

export const readOnlyFieldClass = cn(
  "border-input/60 bg-muted/15 text-foreground flex min-w-0 items-center rounded-md border px-3 text-xs leading-none break-words whitespace-normal",
  workspaceDialogControlHeightClass,
);

export const selectTriggerWrapClass = cn(
  "h-8 min-h-8 !h-8 w-full bg-transparent px-3 py-0 shadow-xs whitespace-normal dark:bg-transparent",
  workspaceDialogControlHeightClass,
  "[&_[data-slot=select-value]]:line-clamp-none [&_[data-slot=select-value]]:whitespace-normal [&_[data-slot=select-value]]:break-words",
);

const itemCardIconShellClass =
  "flex size-9 shrink-0 items-center justify-center rounded-lg border border-border/50 bg-muted/40 text-muted-foreground";

export const itemCardIconToneClass = {
  neutral: itemCardIconShellClass,
  knowledge: cn(
    itemCardIconShellClass,
    "border-sky-500/35 bg-sky-500/10 text-sky-800 dark:text-sky-200",
  ),
  api: cn(
    itemCardIconShellClass,
    "border-violet-500/35 bg-violet-500/10 text-violet-800 dark:text-violet-200",
  ),
  agent: cn(
    itemCardIconShellClass,
    "border-primary/35 bg-primary/10 text-primary",
  ),
} as const;

export const itemCardIconClass = "size-4";

export const itemCardBadgeClass = "h-4 px-1.5 text-[10px] font-normal";
