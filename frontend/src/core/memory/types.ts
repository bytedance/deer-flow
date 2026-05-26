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

export interface SessionFact {
  id: string;
  content: string;
  category: string;
  confidence: number;
  created_at: string;
  source_error: string | null;
}

export interface SessionMemory {
  thread_id: string;
  facts: SessionFact[];
  session_context: Record<string, unknown>;
}

export interface DomainFact {
  id: string;
  content: string;
  domain: string;
  entity_id: string;
  confidence: number;
  created_at: string;
  similarity_score: number;
  adjusted_score: number;
}

export interface DomainFactCreateInput {
  content: string;
  domain: string;
  entity_id: string;
  confidence: number;
}

export interface AuditEntry {
  id: number;
  tenant_id: string;
  user_id: string;
  action: string;
  layer: string;
  fact_id: string;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  created_at: string;
}
