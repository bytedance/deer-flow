import { Skeleton } from "@/components/ui/skeleton";

const STAGGER_MS = 60;

function SkeletonBar({
  className,
  style,
  originRight,
}: {
  className?: string;
  style?: React.CSSProperties;
  originRight?: boolean;
}) {
  return (
    <div
      className={`animate-skeleton-entrance fill-mode-[forwards] overflow-hidden rounded-md ${originRight ? "origin-[right]" : "origin-[left]"} ${className ?? ""}`}
      style={{ opacity: 0, ...style }}
    >
      <Skeleton className="h-full w-full rounded-md" />
    </div>
  );
}

export function MessageListSkeleton() {
  let index = 0;
  return (
    <div className="flex w-full max-w-(--container-width-md) flex-col gap-12 p-8 pt-16">
      <div
        role="human-message"
        className="flex w-[50%] flex-col items-end gap-2 self-end"
      >
        <SkeletonBar
          className="h-6 w-full"
          originRight
          style={{ animationDelay: `${index++ * STAGGER_MS}ms` }}
        />
        <SkeletonBar
          className="h-6 w-[80%]"
          originRight
          style={{ animationDelay: `${index++ * STAGGER_MS}ms` }}
        />
      </div>
      <div role="assistant-message" className="flex flex-col gap-2">
        <SkeletonBar
          className="h-6 w-full"
          style={{ animationDelay: `${index++ * STAGGER_MS}ms` }}
        />
        <SkeletonBar
          className="h-6 w-full"
          style={{ animationDelay: `${index++ * STAGGER_MS}ms` }}
        />
        <SkeletonBar
          className="h-6 w-[70%]"
          style={{ animationDelay: `${index++ * STAGGER_MS}ms` }}
        />
        <SkeletonBar
          className="h-6 w-full"
          style={{ animationDelay: `${index++ * STAGGER_MS}ms` }}
        />
        <SkeletonBar
          className="h-6 w-full"
          style={{ animationDelay: `${index++ * STAGGER_MS}ms` }}
        />
        <SkeletonBar
          className="h-6 w-full"
          style={{ animationDelay: `${index++ * STAGGER_MS}ms` }}
        />
        <SkeletonBar
          className="h-6 w-[60%]"
          style={{ animationDelay: `${index++ * STAGGER_MS}ms` }}
        />
        <SkeletonBar
          className="h-6 w-[40%]"
          style={{ animationDelay: `${index++ * STAGGER_MS}ms` }}
        />
      </div>
    </div>
  );
}
