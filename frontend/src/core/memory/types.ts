export interface MemoryFact {
  id: string;
  content: string;
  category: string;
  confidence: number;
  createdAt: string;
  source: string;
}

export interface MemoryFactInput {
  content: string;
  category: string;
  confidence: number;
}

export interface MemoryFactPatchInput {
  content?: string;
  category?: string;
  confidence?: number;
}

export interface UserMemory {
  version: string;
  lastUpdated: string;
  user: {
    workContext: {
      summary: string;
      updatedAt: string;
    };
    personalContext: {
      summary: string;
      updatedAt: string;
    };
    topOfMind: {
      summary: string;
      updatedAt: string;
    };
  };
  history: {
    recentMonths: {
      summary: string;
      updatedAt: string;
    };
    earlierContext: {
      summary: string;
      updatedAt: string;
    };
    longTermBackground: {
      summary: string;
      updatedAt: string;
    };
  };
  facts: MemoryFact[];
}

export interface BatchFactUpdateInput {
  fact_id: string;
  content?: string;
  category?: string;
  confidence?: number;
}

export interface BatchDeleteInput {
  fact_ids: string[];
}

export interface BatchUpdateInput {
  updates: BatchFactUpdateInput[];
}
