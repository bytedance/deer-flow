import { cn } from "@/lib/utils";

export function StreamingIndicator({
  className,
  size = "normal",
}: {
  className?: string;
  size?: "normal" | "sm";
}) {
  const dotSize = size === "sm" ? "w-1.5 h-1.5 mx-0.5" : "w-2 h-2 mx-1";

  return (
    <div className={cn("flex", className)}>
      <div
        className={cn(
          dotSize,
          "animate-bouncing rounded-full bg-[#a3a1a1] opacity-100",
        )}
      />
      <div
        className={cn(
          dotSize,
          "animate-bouncing rounded-full bg-[#a3a1a1] opacity-100 [animation-delay:0.2s]",
        )}
      />
      <div
        className={cn(
          dotSize,
          "animate-bouncing rounded-full bg-[#a3a1a1] opacity-100 [animation-delay:0.4s]",
        )}
      />
    </div>
  );
}
