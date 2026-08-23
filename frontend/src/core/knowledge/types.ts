export type KnowledgeDataset = {
  id: string;
  name: string;
  description?: string | null;
  document_count?: number;
  chunk_count?: number;
  create_time?: number;
  update_time?: number;
  unstart_count?: number;
  running_count?: number;
  cancel_count?: number;
  done_count?: number;
  fail_count?: number;
  [key: string]: unknown;
};

export type KnowledgeDocument = {
  id: string;
  name: string;
  run?: string;
  progress?: number;
  progress_msg?: string;
  size?: number;
  chunk_count?: number;
  token_count?: number;
  create_time?: number;
  update_time?: number;
  [key: string]: unknown;
};

export type KnowledgeDocumentPage = {
  documents: KnowledgeDocument[];
  total: number;
};

export type CreateKnowledgeDatasetRequest = {
  name: string;
  description?: string;
};

export type FailedKnowledgeDocument = {
  id: string;
  name: string;
};

export type KnowledgeParsingEvent =
  | {
      type: "dataset_parsing_progress";
      datasetId: string;
      unstartCount: number;
      runningCount: number;
      cancelCount: number;
      doneCount: number;
      failCount: number;
    }
  | {
      type: "dataset_parsing_completed";
      datasetId: string;
      doneCount: number;
      failCount: number;
    }
  | {
      type: "dataset_parsing_failed";
      datasetId: string;
      failedDocuments: FailedKnowledgeDocument[];
    };
