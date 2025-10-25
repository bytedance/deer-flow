// Mock store for testing without ESM module dependencies

export const mockUseStore = {
  getState: jest.fn(() => ({
    responding: false,
    messageIds: [] as string[],
    messages: new Map(),
    researchIds: [] as string[],
    researchPlanIds: new Map(),
    researchReportIds: new Map(),
    researchActivityIds: new Map(),
    ongoingResearchId: null,
    openResearchId: null,
    appendMessage: jest.fn(),
    updateMessage: jest.fn(),
    updateMessages: jest.fn(),
  })),
  setState: jest.fn(),
};
