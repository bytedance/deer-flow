import { env } from "@/env";

// Resolve deployment credentials on requests, never while prerendering a build.
// The explicit fetch revalidate below still caches GitHub data for one hour.
export const revalidate = 0;

function isValidCount(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}

/**
 * Return public repository star and fork counts using the server's runtime
 * GitHub token. No input; missing credentials, upstream failures, or invalid
 * star counts yield 204 so the UI hides the counters. Stays outside nginx's
 * /api Gateway proxy.
 */
export async function GET() {
  const token = env.GITHUB_OAUTH_TOKEN;
  const headers = { "Cache-Control": "no-store" };
  if (!token) return new Response(null, { status: 204, headers });

  try {
    const response = await fetch(
      "https://api.github.com/repos/bytedance/deer-flow",
      {
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        next: { revalidate: 3600 },
      },
    );
    if (response.ok) {
      const data = (await response.json()) as {
        stargazers_count?: unknown;
        forks_count?: unknown;
      };
      if (isValidCount(data.stargazers_count)) {
        const payload: { stars: number; forks?: number } = {
          stars: data.stargazers_count,
        };
        if (isValidCount(data.forks_count)) {
          payload.forks = data.forks_count;
        }
        return Response.json(payload, { headers });
      }
    }
  } catch {
    // The counter is optional; do not return upstream errors or credentials.
  }
  return new Response(null, { status: 204, headers });
}
