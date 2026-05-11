export function GET() {
  return Response.json({
    skills: [
      {
        name: "deep-research",
        description:
          "Use this skill BEFORE any content generation task (PPT, design, articles, images, videos, reports). Provides a systematic methodology for conducting thorough, multi-angle web research to gather comprehensive information.",
        license: null,
        category: "public",
        enabled: true,
      },
      {
        name: "frontend-design",
        description:
          "Create distinctive, production-grade frontend interfaces with high design quality. Use this skill when the user asks to build web components, pages, artifacts, posters, or applications (examples include websites, landing pages, dashboards, React components, HTML/CSS layouts, or when styling/beautifying any web UI). Generates creative, polished code and UI design that avoids generic AI aesthetics.",
        license: "Complete terms in LICENSE.txt",
        category: "public",
        enabled: true,
      },
      {
        name: "github-deep-research",
        description:
          "Conduct multi-round deep research on any GitHub Repo. Use when users request comprehensive analysis, timeline reconstruction, competitive analysis, or in-depth investigation of GitHub. Produces structured markdown reports with executive summaries, chronological timelines, metrics analysis, and Mermaid diagrams. Triggers on Github repository URL or open source projects.",
        license: null,
        category: "public",
        enabled: true,
      },
      {
        name: "image-generation",
        description:
          "Use this skill when the user requests to generate, create, imagine, or visualize images including characters, scenes, products, or any visual content. Supports structured prompts and reference images for guided generation.",
        license: null,
        category: "public",
        enabled: true,
      },
      {
        name: "podcast-generation",
        description:
          "Use this skill when the user requests to generate, create, or produce podcasts from text content. Converts written content into a two-host conversational podcast audio format with natural dialogue.",
        license: null,
        category: "public",
        enabled: true,
      },
      {
        name: "ppt-generation",
        description:
          "Use this skill when the user requests to generate, create, or make presentations (PPT/PPTX). Creates visually rich slides by generating images for each slide and composing them into a PowerPoint file.",
        license: null,
        category: "public",
        enabled: true,
      },
      {
        name: "skill-creator",
        description:
          "Guide for creating effective skills. This skill should be used when users want to create a new skill (or update an existing skill) that extends Claude's capabilities with specialized knowledge, workflows, or tool integrations.",
        license: "Complete terms in LICENSE.txt",
        category: "public",
        enabled: true,
      },
      {
        name: "vercel-deploy",
        description:
          'Deploy applications and websites to Vercel. Use this skill when the user requests deployment actions such as "Deploy my app", "Deploy this to production", "Create a preview deployment", "Deploy and give me the link", or "Push this live". No authentication required - returns preview URL and claimable deployment link.',
        license: null,
        category: "public",
        enabled: true,
      },
      {
        name: "video-generation",
        description:
          "Use this skill when the user requests to generate, create, or imagine videos. Supports structured prompts and reference image for guided generation.",
        license: null,
        category: "public",
        enabled: true,
      },
      {
        name: "web-design-guidelines",
        description:
          'Review UI code for Web Interface Guidelines compliance. Use when asked to "review my UI", "check accessibility", "audit design", "review UX", or "check my site against best practices".',
        license: null,
        category: "public",
        enabled: true,
      },
    ],
  });
}
