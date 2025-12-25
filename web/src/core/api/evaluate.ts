// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { resolveServiceURL } from "./resolve-service-url";

/**
 * Report evaluation API client.
 */

export interface EvaluationMetrics {
  word_count: number;
  citation_count: number;
  unique_sources: number;
  image_count: number;
  section_count: number;
  section_coverage_score: number;
  sections_found: string[];
  sections_missing: string[];
  has_title: boolean;
  has_key_points: boolean;
  has_overview: boolean;
  has_citations_section: boolean;
}

export interface LLMEvaluationScores {
  factual_accuracy: number;
  completeness: number;
  coherence: number;
  relevance: number;
  citation_quality: number;
  writing_quality: number;
}

export interface LLMEvaluation {
  scores: LLMEvaluationScores;
  overall_score: number;
  weighted_score: number;
  strengths: string[];
  weaknesses: string[];
  suggestions: string[];
}

export interface EvaluationResult {
  metrics: EvaluationMetrics;
  score: number;
  grade: string;
  llm_evaluation?: LLMEvaluation;
  summary?: string;
}

export interface EvaluateReportRequest {
  content: string;
  query: string;
  report_style?: string;
  use_llm?: boolean;
}

/**
 * Evaluate a report's quality using automated metrics and optionally LLM-as-Judge.
 *
 * @param content - Report markdown content
 * @param query - Original research query
 * @param reportStyle - Report style (academic, news, etc.)
 * @param useLlm - Whether to use LLM for deep evaluation
 * @returns Evaluation result with metrics, score, and grade
 */
export async function evaluateReport(
  content: string,
  query: string,
  reportStyle?: string,
  useLlm?: boolean,
): Promise<EvaluationResult> {
  const response = await fetch(resolveServiceURL("report/evaluate"), {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      content,
      query,
      report_style: reportStyle ?? "default",
      use_llm: useLlm ?? false,
    } satisfies EvaluateReportRequest),
  });

  if (!response.ok) {
    throw new Error(`Evaluation failed: ${response.statusText}`);
  }

  return response.json();
}
