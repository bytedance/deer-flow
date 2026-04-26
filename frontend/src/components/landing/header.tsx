import { StarFilledIcon, GitHubLogoIcon } from "@radix-ui/react-icons";

import { Button } from "@/components/ui/button";
import { NumberTicker } from "@/components/ui/number-ticker";
import { env } from "@/env";

export function Header() {
  return (
    <header className="container-md fixed top-0 right-0 left-0 z-20 mx-auto flex h-16 items-center justify-between backdrop-blur-xs">
      <div className="flex items-center gap-2">
        <a href="https://github.com/bytedance/deer-flow" target="_blank">
          <h1 className="font-serif text-xl">DeerFlow</h1>
        </a>
      </div>
      <div className="relative">
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
          <a href="https://github.com/bytedance/deer-flow" target="_blank">
            <GitHubLogoIcon className="size-4" />
            Star on GitHub
            {env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true" &&
              env.GITHUB_OAUTH_TOKEN && <StarCounter />}
          </a>
        </Button>
      </div>
      <hr className="from-border/0 via-border/70 to-border/0 absolute top-16 right-0 left-0 z-10 m-0 h-px w-full border-none bg-linear-to-r" />
    </header>
  );
}

async function StarCounter() {
  let stars = 10000; // Default value

  try {
    const response = await fetch(
      "https://api.github.com/repos/bytedance/deer-flow",
      {
        headers: env.GITHUB_OAUTH_TOKEN
          ? {
              Authorization: `Bearer ${env.GITHUB_OAUTH_TOKEN}`,
              "Content-Type": "application/json",
            }
          : {},
        next: {
          revalidate: 3600,
        },
      },
    );

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
