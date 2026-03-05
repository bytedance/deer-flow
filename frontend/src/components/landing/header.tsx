import { StarFilledIcon, GitHubLogoIcon } from "@radix-ui/react-icons";

import { Button } from "@/components/ui/button";
import { NumberTicker } from "@/components/ui/number-ticker";
import { useAppConfig } from "@/core/config";
import { env } from "@/env";
import { cn } from "@/lib/utils";

export function Header() {
  const { brand } = useAppConfig();
  const githubUrl = brand.github_url ?? "https://github.com/thinktank-ai/thinktank-ai";

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
        <a href={githubUrl} target="_blank" rel="noreferrer">
          <h1 className="font-serif text-xl">{brand.name}</h1>
        </a>
      </div>
      <div
        className="relative"
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        style={env.IS_ELECTRON ? ({ WebkitAppRegion: "no-drag" } as any) : undefined}
      >
        <div
          className="pointer-events-none absolute inset-0 z-0 h-full w-full rounded-full opacity-30 blur-2xl"
          style={{
            background: "linear-gradient(90deg, #ff80b5 0%, #9089fc 100%)",
            filter: "blur(16px)",
          }}
        />
        <Button
          variant="outline"
          size="sm"
          asChild
          className="group relative z-10"
        >
          <a href={githubUrl} target="_blank" rel="noreferrer">
            <GitHubLogoIcon className="size-4" />
            Star on GitHub
            {env.VITE_STATIC_WEBSITE_ONLY === "true" && (
              <StarCounter githubUrl={githubUrl} />
            )}
          </a>
        </Button>
      </div>
      <hr className="from-border/0 via-border/70 to-border/0 absolute top-16 right-0 left-0 z-10 m-0 h-px w-full border-none bg-linear-to-r" />
    </header>
  );
}

async function StarCounter({ githubUrl }: { githubUrl: string }) {
  let stars = 10000; // Default value

  try {
    const response = await fetch(getGitHubRepoApiUrl(githubUrl), {
      headers: {
        "Content-Type": "application/json",
      },
    });

    if (response.ok) {
      const data = await response.json();
      stars = data.stargazers_count ?? stars; // Update stars if API response is valid
    }
  } catch (error) {
    console.error("Error fetching GitHub stars:", error);
  }
  return (
    <>
      <StarFilledIcon className="size-4 transition-colors duration-300 group-hover:text-yellow-500" />
      {stars && (
        <NumberTicker className="font-mono tabular-nums" value={stars} />
      )}
    </>
  );
}

function getGitHubRepoApiUrl(githubUrl: string): string {
  try {
    const parsed = new URL(githubUrl);
    const [owner, repo] = parsed.pathname.split("/").filter(Boolean);
    if (owner && repo) {
      return `https://api.github.com/repos/${owner}/${repo}`;
    }
  } catch {
    // Fall through to default if URL parsing fails.
  }
  return "https://api.github.com/repos/thinktank-ai/thinktank-ai";
}
