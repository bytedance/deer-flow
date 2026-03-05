import { useAppConfig } from "@/core/config";
import { env } from "@/env";
import { cn } from "@/lib/utils";

export function Header() {
  const { brand } = useAppConfig();

  return (
    <header
      className="container-md fixed top-0 right-0 left-0 z-20 mx-auto flex h-16 items-center justify-between backdrop-blur-xs"
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      style={env.IS_ELECTRON ? ({ WebkitAppRegion: "drag" } as any) : undefined}
    >
      <div
        className={cn("flex items-center gap-2", env.IS_ELECTRON && "pl-20")}
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        style={env.IS_ELECTRON ? ({ WebkitAppRegion: "no-drag" } as any) : undefined}
      >
        <h1 className="font-serif text-xl">{brand.name}</h1>
      </div>
      <hr className="from-border/0 via-border/70 to-border/0 absolute top-16 right-0 left-0 z-10 m-0 h-px w-full border-none bg-linear-to-r" />
    </header>
  );
}
