// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { resolveServiceURL } from "./resolve-service-url";

export interface EnhancePromptRequest {
  prompt: string;
  context?: string;
  report_style?: string;
}

export interface EnhancePromptResponse {
  enhanced_prompt: string;
}

export async function enhancePrompt(
  request: EnhancePromptRequest,
): Promise<string> {
  const response = await fetch(resolveServiceURL("prompt/enhance"), {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    throw new Error(`HTTP error! status: ${response.status}`);
  }

  const data = await response.json();
  console.log("Raw API response:", data); // Debug log

  // The backend now returns the enhanced prompt directly in the result field
  let enhancedPrompt = data.result;

  // If the result is somehow still a JSON object, extract the enhanced_prompt
  if (typeof enhancedPrompt === "object" && enhancedPrompt.enhanced_prompt) {
    enhancedPrompt = enhancedPrompt.enhanced_prompt;
  }

  // If the result is a JSON string, try to parse it
  if (typeof enhancedPrompt === "string") {
    try {
      const parsed = JSON.parse(enhancedPrompt);
      if (parsed.enhanced_prompt) {
        enhancedPrompt = parsed.enhanced_prompt;
      }
    } catch {
      // If parsing fails, use the string as-is (which is what we want)
      console.log("Using enhanced prompt as-is:", enhancedPrompt);
    }
  }

  // Fallback to original prompt if something went wrong
  if (!enhancedPrompt || enhancedPrompt.trim() === "") {
    console.warn("No enhanced prompt received, using original");
    enhancedPrompt = request.prompt;
  }

  return enhancedPrompt;
}
