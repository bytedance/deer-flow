export default function WorkspaceLoading() {
  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center gap-6">
      <div className="flex flex-col items-center gap-4">
        {/* Animated skeleton avatar */}
        <div className="bg-muted size-10 animate-pulse rounded-full" />
        {/* Skeleton text blocks */}
        <div className="flex flex-col items-center gap-2">
          <div className="bg-muted h-4 w-48 animate-pulse rounded" />
          <div className="bg-muted h-3 w-32 animate-pulse rounded opacity-60" />
        </div>
      </div>
      {/* Skeleton message blocks */}
      <div className="w-full max-w-md space-y-4 px-4">
        <div className="flex gap-3">
          <div className="bg-muted size-8 shrink-0 animate-pulse rounded-full" />
          <div className="flex-1 space-y-2">
            <div className="bg-muted h-3 w-3/4 animate-pulse rounded" />
            <div className="bg-muted h-3 w-1/2 animate-pulse rounded" />
          </div>
        </div>
        <div className="flex gap-3">
          <div className="bg-muted size-8 shrink-0 animate-pulse rounded-full" />
          <div className="flex-1 space-y-2">
            <div className="bg-muted h-3 w-5/6 animate-pulse rounded" />
            <div className="bg-muted h-3 w-2/3 animate-pulse rounded" />
            <div className="bg-muted h-3 w-1/3 animate-pulse rounded" />
          </div>
        </div>
      </div>
      <p className="text-muted-foreground text-sm">Loading workspace...</p>
    </div>
  );
}
