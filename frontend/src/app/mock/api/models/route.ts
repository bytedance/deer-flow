export function GET() {
  return Response.json({
    models: [
      {
        id: "doubao-seed-1.8",
        name: "doubao-seed-1.8",
        model: "doubao-seed-1-8",
        display_name: "Doubao Seed 1.8",
        supports_thinking: true,
      },
      {
        id: "deepseek-v4",
        name: "deepseek-v4",
        model: "deepseek-v4-pro",
        display_name: "DeepSeek V4",
        supports_thinking: true,
      },
      {
        id: "gpt-5",
        name: "gpt-5",
        model: "gpt-5",
        display_name: "GPT-5",
        supports_thinking: true,
      },
      {
        id: "gemini-3-pro",
        name: "gemini-3-pro",
        model: "gemini-3-pro",
        display_name: "Gemini 3 Pro",
        supports_thinking: true,
      },
    ],
  });
}
