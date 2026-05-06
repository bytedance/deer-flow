export interface FeedbackSubmission {
  thread_id: string;
  message_id: string;
  rating: number;
  categories?: string[];
  comment?: string;
}

export interface FeedbackSummary {
  total_feedback: number;
  avg_rating: number;
  rating_distribution: Record<string, number>;
  top_categories: { category: string; count: number }[];
}
