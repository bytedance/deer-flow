import {
  CalendarIcon,
  FolderIcon,
  PlusIcon,
  ShuffleIcon,
  TableIcon,
  type LucideIcon,
} from "lucide-react";
import { useCallback } from "react";

import { usePromptInputController } from "@/components/ai-elements/prompt-input";
import { cn } from "@/lib/utils";

interface QuickAction {
  icon: LucideIcon;
  label: string;
  prompt: string;
}

const defaultActions: QuickAction[] = [
  {
    icon: CalendarIcon,
    label: "Research Green Bonds for Coastal Resilience",
    prompt: "Which US municipalities have successfully issued green bonds to fund climate resilience infrastructure? Compare their project outcomes, repayment structures, and lessons learned — particularly for coastal cities under 500,000 population.",
  },
  {
    icon: FolderIcon,
    label: "Analyze Brazil, India, and South Africa Trends",
    prompt: "What are the GDP per capita and life expectancy trends for Brazil, India, and South Africa over the last 20 years? Which country has improved the most?",
  },
  {
    icon: TableIcon,
    label: "Retrieve AAPL Stock Data",
    prompt: "Use AlphaVantage to retrieve the as-traded daily open/high/low/close/volume values of today for AAPL.",
  },
];

interface QuickActionCardProps {
  icon: LucideIcon;
  label: string;
  onClick?: () => void;
  className?: string;
}

function QuickActionCard({
  icon: Icon,
  label,
  onClick,
  className,
}: QuickActionCardProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex flex-1 items-center gap-3 rounded-xl border border-border bg-card/50 px-4 py-4",
        "text-left text-sm font-medium text-foreground/80",
        "transition-all duration-200",
        "hover:border-border/80 hover:bg-card hover:text-foreground",
        "focus:outline-none focus:ring-2 focus:ring-primary/20",
        className,
      )}
    >
      <div className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-muted/50">
        <Icon className="size-5 text-muted-foreground" />
      </div>
      <span className="leading-tight">{label}</span>
    </button>
  );
}

interface QuickActionsProps {
  className?: string;
  actions?: QuickAction[];
}

export function QuickActions({ className, actions = defaultActions }: QuickActionsProps) {
  const { textInput } = usePromptInputController();

  const handleActionClick = useCallback(
    (prompt: string) => {
      textInput.setInput(prompt);
      setTimeout(() => {
        const textarea = document.querySelector<HTMLTextAreaElement>(
          "textarea[name='message']",
        );
        if (textarea) {
          textarea.focus();
        }
      }, 100);
    },
    [textInput],
  );

  return (
    <div className={cn("w-full rounded-xl border border-border bg-card/60 p-4", className)}>
      {/* Header row */}
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2 text-sm font-medium text-muted-foreground">
          <ShuffleIcon className="size-4" />
          <span>Pick a task, any task</span>
        </div>
        {/* Temporarily hidden for demo */}
        {false && (
          <button
            type="button"
            className="flex items-center gap-1 text-sm text-muted-foreground transition-colors hover:text-foreground"
          >
            <PlusIcon className="size-3.5" />
            Customize with plugins
          </button>
        )}
      </div>

      {/* Task cards - 3 in a row */}
      <div className="flex gap-3">
        {actions.map((action) => (
          <QuickActionCard
            key={action.label}
            icon={action.icon}
            label={action.label}
            onClick={() => handleActionClick(action.prompt)}
          />
        ))}
      </div>
    </div>
  );
}
