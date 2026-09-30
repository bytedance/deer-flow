import { env } from "@/env";

// Resolve deployment credentials on requests, never while prerendering a build.
// The explicit fetch revalidate below still caches GitHub data for one hour.
export const revalidate = 0;

/**
 * Return only the public star count using the server's runtime GitHub token.
 * No input; missing credentials, upstream failures, or invalid counts yield 204
 * so the header hides the counter. Stays outside nginx's /api Gateway proxy.
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
      const data = (await response.json()) as { stargazers_count?: unknown };
      if (
        typeof data.stargazers_count === "number" &&
        Number.isSafeInteger(data.stargazers_count) &&
        data.stargazers_count >= 0
      ) {
        return Response.json({ stars: data.stargazers_count }, { headers });
      }
    }
  } catch {
    // The counter is optional; do not return upstream errors or credentials.
  }
  return new Response(null, { status: 204, headers });
}
